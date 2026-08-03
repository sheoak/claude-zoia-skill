"""Command-line bridge between ZOIA .bin patches and editable JSON.

This tool exists so that an AI agent (e.g. Claude Code) or a human can edit
ZOIA patches as plain, well-structured JSON text and write them back to the
binary format the pedal reads.

Workflow
--------
    patch_cli.py setup                          # once per machine
    patch_cli.py decode  my_patch.bin  my_patch.json
    # ...edit my_patch.json (by hand or with an AI agent)...
    patch_cli.py encode  my_patch.json out.bin

Other commands
--------------
    info       Human-readable summary of a .bin (modules, cpu, pages, wiring).
    roundtrip  Decode -> encode -> compare bytes, and report how faithfully
               the encoder reproduces the original.

It wraps PatchBinary (parser) and PatchEncoder (writer) from the ZOIA Librarian
(https://github.com/meanmedianmoge/zoia_lib, GPLv3), which `setup` clones once
into a shared cache. The JSON it emits is exactly the dict produced by
PatchBinary.parse_data, so `encode` can read back anything `decode` wrote.

You can run this from any directory — a patch repo, a folder of .bin files.
The engine is located independently of the current directory.

NOTE ON FIDELITY: the encoder round-trips byte-exact on real patches, so an
unmodified decode -> encode is a no-op. Run `roundtrip` on a patch you have not
worked with before to confirm, and keep a backup before overwriting.
"""

import argparse
import json
import os
import subprocess
import sys

ZOIA_LIB_REPO = "https://github.com/meanmedianmoge/zoia_lib.git"

# Paths on the command line are relative to where the user invoked us, but the
# engine only finds its schemas when the process runs from the zoia_lib root,
# so remember where we started before chdir'ing.
ORIGINAL_CWD = os.getcwd()

PatchBinary = None
PatchEncoder = None


def _cache_root():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(base, "claude-zoia-skill")


def _default_engine_path():
    return os.path.join(_cache_root(), "zoia_lib")


def _looks_like_zoia_lib(path):
    return os.path.isfile(
        os.path.join(path, "zoia_lib", "backend", "patch_binary.py")
    ) and os.path.isfile(
        os.path.join(path, "zoia_lib", "common", "schemas", "ModuleIndex.json")
    )


def find_engine():
    """Locate a zoia_lib checkout, or return None.

    Order: $ZOIA_LIB_PATH, the shared cache, the current directory (so an
    existing checkout you are already sitting in is used as-is).
    """
    candidates = []
    env = os.environ.get("ZOIA_LIB_PATH")
    if env:
        candidates.append(os.path.expanduser(env))
    candidates.append(_default_engine_path())
    candidates.append(ORIGINAL_CWD)

    for path in candidates:
        if path and _looks_like_zoia_lib(path):
            return os.path.abspath(path)
    return None


def load_engine():
    """Import the parser/encoder, chdir'ing so their schema lookups resolve."""
    global PatchBinary, PatchEncoder

    root = find_engine()
    if root is None:
        sys.stderr.write(
            "error: the ZOIA patch engine (zoia_lib) was not found.\n"
            "\n"
            "Install it once, into a shared cache used by every patch repo:\n"
            "    python3 {} setup\n"
            "\n"
            "Or point at an existing checkout:\n"
            "    export ZOIA_LIB_PATH=/path/to/zoia_lib\n".format(sys.argv[0])
        )
        raise SystemExit(2)

    sys.path.insert(0, root)
    # zoia_lib resolves its ModuleIndex.json relative to the working directory.
    os.chdir(root)

    from zoia_lib.backend.patch_binary import PatchBinary as _PatchBinary
    from zoia_lib.backend.patch_encode import PatchEncoder as _PatchEncoder

    PatchBinary = _PatchBinary
    PatchEncoder = _PatchEncoder


def _abs(path):
    """Resolve a user-supplied path against the directory they invoked us from."""
    if path is None:
        return None
    return path if os.path.isabs(path) else os.path.join(ORIGINAL_CWD, path)


def _read_bin(path):
    with open(path, "rb") as f:
        return f.read()


def _summary_lines(patch):
    """Return a list of human-readable lines describing a parsed patch."""
    meta = patch.get("meta", {})
    lines = [
        "name:        {}".format(patch.get("name")),
        "modules:     {}".format(meta.get("n_modules", len(patch.get("modules", [])))),
        "connections: {}".format(meta.get("n_connections", len(patch.get("connections", [])))),
        "pages:       {}".format(meta.get("n_pages", len(patch.get("pages", [])))),
        "starred:     {}".format(meta.get("n_starred", len(patch.get("starred", [])))),
        "total cpu:   {}".format(meta.get("cpu")),
        "",
        "Modules:",
    ]
    for m in patch.get("modules", []):
        lines.append(
            "  [{number}] {name} (idx {mod_idx}, {category})"
            "  page {page}  blocks {position}  color {color}".format(
                number=m.get("number"),
                name=m.get("name"),
                mod_idx=m.get("mod_idx"),
                category=m.get("category"),
                page=m.get("page"),
                position=m.get("position"),
                color=m.get("color"),
            )
        )
    if patch.get("connections"):
        lines.append("")
        lines.append("Connections (source -> destination @ strength):")
        for c in patch["connections"]:
            lines.append(
                "  {} -> {}  @ {}".format(
                    c.get("source"), c.get("destination"), c.get("strength")
                )
            )
    return lines


def cmd_setup(args):
    """Clone (or update) the engine once, in a cache shared by all patch repos."""
    target = _abs(args.path) if args.path else _default_engine_path()

    if _looks_like_zoia_lib(target):
        if not args.update:
            print("Engine already installed at {}".format(target))
            print("Re-run with --update to pull the latest version.")
            return 0
        print("Updating engine at {}".format(target))
        return subprocess.call(["git", "-C", target, "pull", "--ff-only"])

    if os.path.exists(target) and os.listdir(target):
        sys.stderr.write(
            "error: {} exists and is not a zoia_lib checkout.\n".format(target)
        )
        return 2

    os.makedirs(os.path.dirname(target), exist_ok=True)
    print("Cloning the ZOIA patch engine into {}".format(target))
    print("(shallow clone of {}, ~18 MB, done once per machine)".format(ZOIA_LIB_REPO))
    rc = subprocess.call(
        ["git", "clone", "--depth", "1", ZOIA_LIB_REPO, target]
    )
    if rc != 0:
        return rc

    if not _looks_like_zoia_lib(target):
        sys.stderr.write("error: clone finished but the checkout looks incomplete.\n")
        return 2

    print("Engine ready. Patch commands now work from any directory.")
    return 0


def cmd_decode(args):
    load_engine()
    in_path = _abs(args.input)
    raw = _read_bin(in_path)
    patch = PatchBinary().parse_data(raw)
    out_path = _abs(args.output) or (in_path.rsplit(".", 1)[0] + ".json")
    with open(out_path, "w") as f:
        json.dump(patch, f, indent=2)
    print("Decoded {} -> {}".format(args.input, out_path))
    print("\n".join(_summary_lines(patch)))
    return 0


def cmd_encode(args):
    load_engine()
    in_path = _abs(args.input)
    with open(in_path) as f:
        patch = json.load(f)
    out_path = _abs(args.output) or (in_path.rsplit(".", 1)[0] + ".bin")
    data = PatchEncoder().encode(
        patch, output_path=out_path, param_order_mode=args.param_order
    )
    print("Encoded {} -> {} ({} bytes)".format(args.input, out_path, len(data)))
    return 0


def cmd_info(args):
    load_engine()
    patch = PatchBinary().parse_data(_read_bin(_abs(args.input)))
    print("\n".join(_summary_lines(patch)))
    return 0


def cmd_roundtrip(args):
    """Decode then re-encode a .bin and report how faithfully it reproduces."""
    load_engine()
    original = _read_bin(_abs(args.input))
    patch = PatchBinary().parse_data(original)
    encoded = bytes(PatchEncoder().encode(patch, param_order_mode=args.param_order))

    print("original bytes: {}".format(len(original)))
    print("encoded bytes:  {}".format(len(encoded)))

    overlap = min(len(original), len(encoded))
    diffs = [i for i in range(overlap) if original[i] != encoded[i]]
    print("differing bytes (in overlap): {}".format(len(diffs)))
    if len(original) != len(encoded):
        print("LENGTH MISMATCH: {} vs {}".format(len(original), len(encoded)))

    # group consecutive diff offsets into ranges for readability
    ranges = []
    for i in diffs:
        if ranges and i == ranges[-1][1] + 1:
            ranges[-1][1] = i
        else:
            ranges.append([i, i])
    if ranges:
        print("diff ranges (offset: orig -> enc):")
        for s, e in ranges[: args.max_ranges]:
            print(
                "  {:>6}-{:<6} {} -> {}".format(
                    s, e + 1, original[s : e + 1].hex(), encoded[s : e + 1].hex()
                )
            )
        if len(ranges) > args.max_ranges:
            print("  ... {} more ranges".format(len(ranges) - args.max_ranges))

    # can the encoded output be parsed back?
    try:
        reparsed = PatchBinary().parse_data(encoded)
        semantic_ok = reparsed == patch
        print("re-decodes without error: YES")
        print("re-decoded dict equals original dict: {}".format(semantic_ok))
    except Exception as e:  # noqa: BLE001 - study/report only
        print("re-decodes without error: NO ({}: {})".format(type(e).__name__, e))

    byte_exact = not diffs and len(original) == len(encoded)
    print("\nVERDICT: {}".format("byte-exact" if byte_exact else "NOT byte-exact"))
    return 0 if byte_exact else 1


def cmd_where(args):
    """Report which engine checkout would be used, for troubleshooting."""
    root = find_engine()
    if root is None:
        print("engine: NOT FOUND (run `setup`)")
        print("would install to: {}".format(_default_engine_path()))
        return 2
    print("engine: {}".format(root))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="patch_cli.py",
        description="Convert ZOIA .bin patches to/from editable JSON.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser(
        "setup", help="clone the patch engine once into a shared cache"
    )
    s.add_argument(
        "path", nargs="?", help="install location (default: ~/.cache/claude-zoia-skill)"
    )
    s.add_argument("--update", action="store_true", help="pull an existing checkout")
    s.set_defaults(func=cmd_setup)

    d = sub.add_parser("decode", help="binary .bin -> editable .json")
    d.add_argument("input", help="path to the .bin patch")
    d.add_argument("output", nargs="?", help="output .json (default: <input>.json)")
    d.set_defaults(func=cmd_decode)

    e = sub.add_parser("encode", help="edited .json -> binary .bin")
    e.add_argument("input", help="path to the .json patch")
    e.add_argument("output", nargs="?", help="output .bin (default: <input>.bin)")
    e.add_argument(
        "--param-order",
        default="order",
        choices=["order", "saved"],
        help="parameter serialization mode passed to PatchEncoder",
    )
    e.set_defaults(func=cmd_encode)

    i = sub.add_parser("info", help="print a human-readable patch summary")
    i.add_argument("input", help="path to the .bin patch")
    i.set_defaults(func=cmd_info)

    r = sub.add_parser("roundtrip", help="check encoder fidelity for a .bin")
    r.add_argument("input", help="path to the .bin patch")
    r.add_argument("--param-order", default="order", choices=["order", "saved"])
    r.add_argument("--max-ranges", type=int, default=20, help="diff ranges to show")
    r.set_defaults(func=cmd_roundtrip)

    w = sub.add_parser("where", help="show which engine checkout is in use")
    w.set_defaults(func=cmd_where)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
