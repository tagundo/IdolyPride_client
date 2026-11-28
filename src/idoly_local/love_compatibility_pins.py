"""Runtime-only exact compatibility proof pin; never an input to its compiler.

The owned remote comparison must produce and independently read back the small
proof before this sentinel is replaced. Unknown latest evidence is fail-closed.
"""
COMPATIBILITY_SHA256 = '3a49ffe031f11dca78caad50605c5861c5c994b79f125fda4b14791995cc8e5f'
