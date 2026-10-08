#!/bin/sh
# Refresh the translation catalogues from the sources and compile them.
#
#   tools/update_translations.sh
#
# pyside6-lupdate keeps existing translations and marks changed sources unfinished;
# pyside6-lrelease writes the .qm files that ship in the wheel.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
bin="$root/.venv/bin"
if [ ! -x "$bin/pyside6-lupdate" ]; then
    bin=$(dirname -- "$(command -v pyside6-lupdate)")
fi

cd "$root"
languages="ru de es fr zh_CN"

for lang in $languages; do
    ts="src/anchorage/i18n/anchorage_$lang.ts"
    "$bin/pyside6-lupdate" -extensions py -no-obsolete -locations none -source-language en \
        -target-language "$lang" src/anchorage -ts "$ts"
    "$bin/pyside6-lrelease" "$ts" -qm "src/anchorage/i18n/anchorage_$lang.qm"
done
