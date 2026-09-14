from __future__ import annotations

from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trusted_services import (
    Availability,
    EndpointAuthorization,
    EndpointRecord,
    LifecycleError,
    LifecycleState,
    OwnedResource,
    OwnerSet,
    ResourcePresence,
    ResourceRegistry,
    ResolvedServicePlan,
    ServiceFamily,
    ServiceLifecycle,
    ServicePlan,
    ServiceScope,
    SharedServiceRecord,
)


DIGEST = "sha256:" + "1" * 64
IMAGE = "example@sha256:" + "2" * 64


def plan(*, scope=ServiceScope.SHARED_SESSION, availability=None, state_schema=1,
         fixed_parameters=None, image_role="service", uid=1000):
    return ServicePlan(
        role="example",
        family=ServiceFamily.COMMAND_PROXY,
        scope=scope,
        availability=availability,
        adapter="example-adapter",
        adapter_identity=DIGEST,
        state_schema=state_schema,
        fixed_parameters={"limit": 3} if fixed_parameters is None else fixed_parameters,
        endpoint_kinds=("unix-socket",),
        image_role=image_role,
        image_uid=uid if image_role else None,
        image_gid=1000 if image_role else None,
    )


def lifecycle(service_plan, owner="owner-1", owners=None):
    image = IMAGE if service_plan.image_role else None
    return ServiceLifecycle(service_plan.resolve(adapter_bytes=b"adapter", image=image),
                            owner, owners or OwnerSet())


def resource(identity, events, *, owner="owner", presence=ResourcePresence.OWNED,
             depends_on=(), remove=None):
    action = remove or (lambda: events.append(identity))
    return OwnedResource(identity, owner, lambda: presence, action, depends_on)


class ServicePlanTest(unittest.TestCase):
    def test_rejects_authority_ambiguity_before_resolution(self):
        with self.assertRaisesRegex(LifecycleError, "shared services are always required"):
            plan(availability=Availability.BEST_EFFORT)
        with self.assertRaisesRegex(LifecycleError, "require availability"):
            plan(scope=ServiceScope.AGENT_LAUNCH)
        with self.assertRaisesRegex(LifecycleError, "canonical"):
            ServicePlan("../service", ServiceFamily.COMMAND_PROXY,
                        ServiceScope.SHARED_SESSION, "adapter", DIGEST, 1)

    def test_rejects_malformed_typed_and_image_bound_values(self):
        invalid = (
            lambda: plan(uid="1000"),
            lambda: plan(uid=1.5),
            lambda: plan(fixed_parameters=[]),
            lambda: ServicePlan("example", "command-proxy", ServiceScope.SHARED_SESSION,
                                "adapter", DIGEST, 1),
        )
        for construct in invalid:
            with self.subTest(construct=construct), self.assertRaises(LifecycleError):
                construct()
        with self.assertRaisesRegex(LifecycleError, "immutable digest"):
            plan().resolve(adapter_bytes=b"adapter", image="example:latest")

    def test_implementation_identity_covers_inputs_not_state_schema(self):
        base = plan().resolve(adapter_bytes=b"adapter", image=IMAGE)
        same = plan(state_schema=2).resolve(adapter_bytes=b"adapter", image=IMAGE)
        self.assertEqual(base.implementation_identity, same.implementation_identity)
        variants = (
            plan().resolve(adapter_bytes=b"changed", image=IMAGE),
            plan(fixed_parameters={"limit": 4}).resolve(adapter_bytes=b"adapter", image=IMAGE),
            plan().resolve(adapter_bytes=b"adapter", image="other@sha256:" + "3" * 64),
            plan(uid=1001).resolve(adapter_bytes=b"adapter", image=IMAGE),
        )
        for variant in variants:
            self.assertNotEqual(base.implementation_identity, variant.implementation_identity)

    def test_resolved_plans_cannot_bypass_resolution(self):
        with self.assertRaisesRegex(LifecycleError, "must be created"):
            ResolvedServicePlan(plan(), None, DIGEST, object())

    def test_nested_plan_inputs_are_immutable_snapshots(self):
        parameters = {"limits": [1, {"requests": 2}]}
        service_plan = plan(fixed_parameters=parameters)
        identity = service_plan.resolve(adapter_bytes=b"adapter", image=IMAGE).implementation_identity
        parameters["limits"][1]["requests"] = 99
        self.assertEqual(2, service_plan.fixed_parameters["limits"][1]["requests"])
        self.assertEqual(identity, service_plan.resolve(
            adapter_bytes=b"adapter", image=IMAGE).implementation_identity)
        with self.assertRaises(TypeError):
            service_plan.fixed_parameters["other"] = True


class LifecycleTransitionTest(unittest.TestCase):
    def drive(self, service, states):
        for state in states:
            service.transition(state)

    def test_shared_required_and_best_effort_paths_are_distinct(self):
        shared = lifecycle(plan())
        self.drive(shared, (LifecycleState.RESOLVED, LifecycleState.PREPARING,
                            LifecycleState.STARTING, LifecycleState.READY,
                            LifecycleState.PUBLISHED, LifecycleState.STOPPING,
                            LifecycleState.REMOVED))
        required = lifecycle(plan(scope=ServiceScope.AGENT_LAUNCH,
                                  availability=Availability.REQUIRED))
        self.drive(required, (LifecycleState.RESOLVED, LifecycleState.PREPARING,
                              LifecycleState.STARTING, LifecycleState.READY,
                              LifecycleState.ATTACHED, LifecycleState.STOPPING,
                              LifecycleState.REMOVED))
        best_effort = lifecycle(plan(scope=ServiceScope.AGENT_LAUNCH,
                                     availability=Availability.BEST_EFFORT))
        self.drive(best_effort, (LifecycleState.RESOLVED, LifecycleState.PREPARING,
                                 LifecycleState.STARTING))
        best_effort.transition(
            LifecycleState.ATTACHED,
            authorization=EndpointAuthorization("owner-1", ("socket-1",)),
        )
        self.drive(best_effort, (LifecycleState.READY, LifecycleState.STOPPING,
                                 LifecycleState.REMOVED))

    def test_rejected_transition_does_not_commit_authorization(self):
        service = lifecycle(plan(scope=ServiceScope.AGENT_LAUNCH,
                                 availability=Availability.BEST_EFFORT))
        authorization = EndpointAuthorization("owner-1", ("socket-1",))
        with self.assertRaisesRegex(LifecycleError, "invalid lifecycle transition"):
            service.transition(LifecycleState.ATTACHED, authorization=authorization)
        self.assertIsNone(service.authorization)
        self.assertEqual(LifecycleState.PLANNED, service.state)
        self.drive(service, (LifecycleState.RESOLVED, LifecycleState.PREPARING,
                             LifecycleState.STARTING))
        with self.assertRaisesRegex(LifecycleError, "invalid lifecycle transition"):
            service.transition(LifecycleState.ATTACHED)

    def test_wrong_authorization_owner_and_owner_reuse_fail_closed(self):
        owners = OwnerSet()
        service = lifecycle(plan(scope=ServiceScope.AGENT_LAUNCH,
                                 availability=Availability.BEST_EFFORT), owners=owners)
        self.drive(service, (LifecycleState.RESOLVED, LifecycleState.PREPARING,
                             LifecycleState.STARTING))
        with self.assertRaisesRegex(LifecycleError, "owner mismatch"):
            service.transition(LifecycleState.ATTACHED,
                               authorization=EndpointAuthorization("other", ("socket",)))
        with self.assertRaisesRegex(LifecycleError, "already used"):
            lifecycle(plan(), owners=owners)

    def test_failure_and_recovery_paths_are_terminal_except_cleanup_retry(self):
        for failure_state in (LifecycleState.PLANNED, LifecycleState.RESOLVED,
                              LifecycleState.PREPARING, LifecycleState.STARTING,
                              LifecycleState.READY):
            with self.subTest(failure_state=failure_state):
                service = lifecycle(plan())
                path = [LifecycleState.RESOLVED, LifecycleState.PREPARING,
                        LifecycleState.STARTING, LifecycleState.READY]
                for state in path[:path.index(failure_state) + 1] if failure_state in path else ():
                    service.transition(state)
                service.transition(LifecycleState.FAILED)
                service.transition(LifecycleState.STOPPING)
                service.transition(LifecycleState.CLEANUP_FAILED)
                service.transition(LifecycleState.STOPPING)
                service.transition(LifecycleState.REMOVED)


class ResourceRegistryTest(unittest.TestCase):
    def test_registration_survives_later_failure_and_stops_after_cleanup_begins(self):
        registry = ResourceRegistry("owner")
        registry.register(resource("network:one", [], presence=ResourcePresence.ABSENT))
        self.assertEqual(("network:one",), registry.identities)
        registry.cleanup(1)
        with self.assertRaisesRegex(LifecycleError, "cleanup has started"):
            registry.register(resource("network:two", []))

    def test_cleanup_orders_dependents_and_runs_independent_removals_concurrently(self):
        registry = ResourceRegistry("owner")
        events = []
        lock = threading.Lock()
        rendezvous = threading.Barrier(2)

        def independent(name):
            rendezvous.wait(timeout=2)
            with lock:
                events.append(name)

        registry.register(resource("network:one", events))
        registry.register(resource("container:a", events, depends_on=("network:one",),
                                   remove=lambda: independent("container:a")))
        registry.register(resource("container:b", events, depends_on=("network:one",),
                                   remove=lambda: independent("container:b")))
        result = registry.cleanup(37)
        self.assertEqual(37, result.primary_status)
        self.assertFalse(result.failures)
        self.assertFalse(result.remaining)
        self.assertEqual("network:one", events[-1])

    def test_failed_dependent_preserves_prerequisite_but_unrelated_branch_cleans(self):
        registry = ResourceRegistry("owner")
        events = []

        def fail():
            raise RuntimeError("token=secret-value")

        registry.register(resource("network:blocked", events))
        registry.register(resource("container:blocked", events,
                                   depends_on=("network:blocked",), remove=fail))
        registry.register(resource("network:independent", events))
        registry.register(resource("container:independent", events,
                                   depends_on=("network:independent",)))
        result = registry.cleanup(23)
        self.assertEqual(23, result.primary_status)
        self.assertEqual(("container:blocked", "network:blocked"), result.remaining)
        self.assertEqual("removal-failed:RuntimeError", result.failures[0].code)
        self.assertNotIn("secret-value", repr(result))
        self.assertIn("container:independent", events)
        self.assertIn("network:independent", events)
        self.assertNotIn("network:blocked", events)

    def test_cleanup_retry_and_concurrent_call_remove_non_idempotent_resource_once(self):
        registry = ResourceRegistry("owner")
        calls = 0
        calls_lock = threading.Lock()

        def remove():
            nonlocal calls
            with calls_lock:
                calls += 1
                if calls > 1:
                    raise AssertionError("removed twice")
            time.sleep(0.02)

        registry.register(resource("container:one", [], remove=remove))
        results = []
        threads = [threading.Thread(target=lambda: results.append(registry.cleanup(0)))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, calls)
        self.assertTrue(all(not result.remaining for result in results))
        self.assertFalse(registry.cleanup(0).remaining)

    def test_process_control_exceptions_are_not_aggregated(self):
        registry = ResourceRegistry("owner")

        def interrupt():
            raise KeyboardInterrupt()

        registry.register(resource("container:one", [], remove=interrupt))
        with self.assertRaises(KeyboardInterrupt):
            registry.cleanup(0)
        self.assertEqual(("container:one",), registry.identities)

    def test_owner_mismatch_is_retained_without_invoking_remove(self):
        removed = []
        registry = ResourceRegistry("owner")
        registry.register(resource("container:one", removed,
                                   presence=ResourcePresence.MISMATCHED))
        result = registry.cleanup(0)
        self.assertEqual(("container:one",), result.remaining)
        self.assertEqual("resource-owner-mismatch", result.failures[0].code)
        self.assertFalse(removed)

    def test_registration_rejects_wrong_owner_duplicates_and_unknown_dependencies(self):
        registry = ResourceRegistry("owner")
        registry.register(resource("network:one", []))
        with self.assertRaisesRegex(LifecycleError, "does not match"):
            registry.register(resource("network:wrong", [], owner="other"))
        with self.assertRaisesRegex(LifecycleError, "already registered"):
            registry.register(resource("network:one", []))
        with self.assertRaisesRegex(LifecycleError, "not registered"):
            registry.register(resource("container:one", [], depends_on=("network:missing",)))


class SharedServiceRecordTest(unittest.TestCase):
    def record(self, transport=None):
        return SharedServiceRecord(
            "codex", ServiceFamily.AUTHENTICATED_EGRESS, DIGEST, 3,
            "runtime-owner", "recovery-owner",
            (EndpointRecord("http", "socket-volume:12",
                            transport or {"volume": {"name": "volume-12"}}),),
            "session-token",
        )

    def test_round_trip_is_strict_and_nested_values_are_snapshots(self):
        transport = {"volume": {"name": "volume-12"}}
        record = self.record(transport)
        transport["volume"]["name"] = "substituted"
        self.assertEqual("volume-12", record.endpoints[0].transport["volume"]["name"])
        encoded = record.to_mapping()
        decoded = SharedServiceRecord.from_mapping("codex", encoded)
        encoded["endpoints"][0]["transport"]["volume"]["name"] = "changed"
        self.assertEqual("volume-12", decoded.endpoints[0].transport["volume"]["name"])
        encoded["unexpected"] = True
        with self.assertRaisesRegex(LifecycleError, "invalid fields"):
            SharedServiceRecord.from_mapping("codex", encoded)

    def test_malformed_records_consistently_raise_lifecycle_error(self):
        malformed = (
            None,
            {},
            {"family": "unknown", "implementation_identity": DIGEST, "state_schema": 1,
             "runtime_owner": "owner", "recovery_identity": "recovery", "endpoints": []},
            {"family": "command-proxy", "implementation_identity": DIGEST,
             "state_schema": "1", "runtime_owner": "owner",
             "recovery_identity": "recovery", "endpoints": [None]},
        )
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(LifecycleError):
                SharedServiceRecord.from_mapping("example", value)


if __name__ == "__main__":
    unittest.main()
