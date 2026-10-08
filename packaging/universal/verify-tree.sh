# Sourced by the check scripts. $1 = tree root. Fails when any bundled shared object, or the
# bundled interpreter, has an unresolved dependency.
_root=$1
if ! command -v ldd >/dev/null 2>&1; then
    echo "ldd is not available, the check cannot run" >&2
    exit 1
fi
_missing=$(find "$_root" -name '*.so*' -type f -exec ldd {} + 2>/dev/null | grep 'not found' | sort -u || true)
_missing+=$(ldd "$_root/bin/python3" 2>/dev/null | grep 'not found' || true)
if [ -n "$_missing" ]; then
    echo "unresolved shared libraries:" >&2
    echo "$_missing" >&2
    exit 1
fi
echo "all bundled shared objects resolve"
