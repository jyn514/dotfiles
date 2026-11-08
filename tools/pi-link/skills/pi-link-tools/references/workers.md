# Worker integration

Read for manager-delivered worker messages, worker callbacks, or questions about the configured worker tool surface.
Apply the [common authority rules](../SKILL.md) and [messaging procedure](messaging.md) to messages.

These rules apply only when a supported manager/child bridge exposes `link_send` with `to: { authorOf: messageId }` and delivers attributed messages to workers.
The installed `pi-codex-subagents` manager/child bridge supplies this capability; without it, worker delivery is unsupported.

## Reply to a manager-delivered worker message

Without full pi-link, the manager helper exposes only author-targeted `link_send`, which addresses the author of a message actually delivered to that worker.
Ask the delivered author only for clarification that can change the next action, or send an answer they requested.
Send normal task completions through the parent channel.
Private answers go only to the requesting worker, not siblings or the parent's model context.
An admitted author-targeted follow-up can reopen a completed worker through its owning manager without changing its assignment.
The reopened episode’s final answer returns privately to its requester; a submitted explicit reply suppresses that automatic answer.
Automatic answers do not themselves request another automatic answer.
Parent waits retain the original assignment result, and the owner and siblings receive no routine completion.
Failed, interrupted, suspended, and paused workers must not resume.
Broadcasts remain active-only, and helper-only communication does not require an independent child pi-link connection.

## Use other tools only when configured

Other link tools and an independent connection are available when pi-link is enabled and the template's tool list permits them.
Follow the configured tool surface; do not infer a reply-only restriction from worker status.

## Independent worker questions

Several workers may independently ask the same question.
Do not add semantic deduplication, a suppression registry, or a wait period.

