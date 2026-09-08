"""One prompt-protected login Keychain item, using macOS Security directly.

The file-based Keychain API is intentional: its empty trusted-application ACL
requires approval without granting a Python interpreter or security(1) access.
No secret is passed to a child process, written to a file, or included in errors.
"""

from contextlib import ExitStack
import ctypes as c
from pathlib import Path
import sys


class KeychainError(ValueError):
    pass


class Keychain:
    SERVICE = b"codex-sandbox"
    ACCOUNT = b"github-token"

    def __init__(self, path=None):
        if sys.platform != "darwin":
            raise KeychainError("GitHub Keychain provisioning requires macOS")
        self.path = path or Path.home() / "Library/Keychains/login.keychain-db"
        self.cf = c.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.sec = c.CDLL("/System/Library/Frameworks/Security.framework/Security")
        pointer = c.c_void_p
        ref = c.POINTER(pointer)
        self.bind(self.cf, "CFRelease", None, pointer)
        self.bind(self.cf, "CFStringCreateWithCString", pointer, pointer, c.c_char_p, c.c_uint32)
        self.bind(self.cf, "CFDataCreate", pointer, pointer, c.c_char_p, c.c_long)
        self.bind(self.cf, "CFArrayCreate", pointer, pointer, pointer, c.c_long, pointer)
        self.bind(self.cf, "CFArrayGetCount", c.c_long, pointer)
        self.bind(self.cf, "CFArrayGetValueAtIndex", pointer, pointer, c.c_long)
        self.bind(self.cf, "CFDictionaryCreateMutable", pointer, pointer, c.c_long, pointer, pointer)
        self.bind(self.cf, "CFDictionarySetValue", None, pointer, pointer, pointer)
        self.bind(self.sec, "SecKeychainOpen", c.c_int32, c.c_char_p, ref)
        self.bind(self.sec, "SecAccessCreate", c.c_int32, pointer, pointer, ref)
        self.bind(self.sec, "SecItemAdd", c.c_int32, pointer, ref)
        self.bind(self.sec, "SecKeychainFindGenericPassword", c.c_int32,
                  pointer, c.c_uint32, c.c_char_p, c.c_uint32, c.c_char_p, pointer, pointer, ref)
        self.bind(self.sec, "SecKeychainItemCopyAccess", c.c_int32, pointer, ref)
        self.bind(self.sec, "SecAccessCopyMatchingACLList", pointer, pointer, pointer)
        self.bind(self.sec, "SecACLCopyContents", c.c_int32, pointer, ref, ref, c.POINTER(c.c_uint32))
        self.bind(self.sec, "SecKeychainItemCopyAttributesAndData", c.c_int32,
                  pointer, pointer, pointer, pointer, c.POINTER(c.c_uint32), ref)
        self.bind(self.sec, "SecKeychainItemFreeAttributesAndData", c.c_int32, pointer, pointer)

    @staticmethod
    def bind(library, name, result, *arguments):
        function = getattr(library, name)
        function.restype = result
        function.argtypes = arguments

    @staticmethod
    def check(status):
        if status:
            raise KeychainError(f"Keychain operation failed (OSStatus {status}); access denied or item unavailable")

    def constant(self, name):
        return c.c_void_p.in_dll(self.sec, name)

    def owned(self, stack, value):
        if not value:
            raise KeychainError("Keychain returned a missing object")
        stack.callback(self.cf.CFRelease, value)
        return value

    def open(self, stack):
        keychain = c.c_void_p()
        self.check(self.sec.SecKeychainOpen(bytes(self.path), c.byref(keychain)))
        return self.owned(stack, keychain)

    def find(self, stack):
        item = c.c_void_p()
        self.check(self.sec.SecKeychainFindGenericPassword(self.open(stack),
            len(self.SERVICE), self.SERVICE, len(self.ACCOUNT), self.ACCOUNT,
            None, None, c.byref(item)))
        return self.owned(stack, item)

    def import_token(self, token):
        validate_token(token)
        with ExitStack() as stack:
            def string(value):
                return self.owned(stack, self.cf.CFStringCreateWithCString(None, value, 0x08000100))
            access = c.c_void_p()
            empty = self.owned(stack, self.cf.CFArrayCreate(None, None, 0, None))
            label = string(b"codex-sandbox/github-token")
            self.check(self.sec.SecAccessCreate(label, empty, c.byref(access)))
            self.owned(stack, access)
            data = self.owned(stack, self.cf.CFDataCreate(None, token, len(token)))
            attributes = self.owned(stack, self.cf.CFDictionaryCreateMutable(None, 0, None, None))
            # Null dictionary callbacks borrow values; ExitStack keeps every
            # value alive until the synchronous SecItemAdd has completed.
            for key, value in {
                "kSecClass": self.constant("kSecClassGenericPassword"),
                "kSecAttrService": string(self.SERVICE),
                "kSecAttrAccount": string(self.ACCOUNT),
                "kSecAttrLabel": label,
                "kSecAttrAccess": access,
                "kSecValueData": data,
                "kSecUseKeychain": self.open(stack),
            }.items():
                self.cf.CFDictionarySetValue(attributes, self.constant(key), value)
            # Duplicate items fail; import never overwrites an existing secret.
            self.check(self.sec.SecItemAdd(attributes, None))

    def check_access(self, stack, item):
        access = c.c_void_p()
        self.check(self.sec.SecKeychainItemCopyAccess(item, c.byref(access)))
        self.owned(stack, access)
        acls = self.owned(stack, self.sec.SecAccessCopyMatchingACLList(
            access, self.constant("kSecACLAuthorizationDecrypt")))
        if self.cf.CFArrayGetCount(acls) == 0:
            raise KeychainError("Keychain item has no explicit decrypt ACL")
        for index in range(self.cf.CFArrayGetCount(acls)):
            apps, description, prompt = c.c_void_p(), c.c_void_p(), c.c_uint32()
            self.check(self.sec.SecACLCopyContents(self.cf.CFArrayGetValueAtIndex(acls, index),
                c.byref(apps), c.byref(description), c.byref(prompt)))
            if description:
                self.owned(stack, description)
            if apps:
                self.owned(stack, apps)
            # NULL trusts all applications; a nonempty array trusts named apps.
            if not apps or self.cf.CFArrayGetCount(apps):
                raise KeychainError("Keychain item permits unprompted access; remove trusted applications in Keychain Access")

    def retrieve(self):
        with ExitStack() as stack:
            item = self.find(stack)
            self.check_access(stack, item)
            size, data = c.c_uint32(), c.c_void_p()
            self.check(self.sec.SecKeychainItemCopyAttributesAndData(item, None, None, None,
                c.byref(size), c.byref(data)))
            try:
                token = c.string_at(data, size.value)
                validate_token(token)
                return token
            finally:
                self.sec.SecKeychainItemFreeAttributesAndData(None, data)


def validate_token(token):
    if not isinstance(token, bytes) or not 1 <= len(token) <= 16384 or any(byte in token for byte in (0, 10, 13)):
        raise KeychainError("GitHub token must be a nonempty single line of at most 16384 bytes")
