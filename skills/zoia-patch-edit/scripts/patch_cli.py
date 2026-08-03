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
import re
import struct
import subprocess
import sys

ZOIA_LIB_REPO = "https://github.com/meanmedianmoge/zoia_lib.git"

# Patches on a ZOIA SD card are named <slot>_zoia_<name>.bin, and a slot holds
# exactly one file.
SLOT_RE = re.compile(r"^(\d{3})_zoia_(.+)\.bin$", re.IGNORECASE)

# Names live in a fixed 16-byte field. Which characters actually survive it
# depends on the engine, so it is measured rather than assumed — see
# _probe_names below.
NAME_BYTES = 16


# Rather than hard-code the two defects above, probe the engine in use: a
# patched or newer zoia_lib may handle characters this one cannot, and the
# check must not refuse names such an engine stores perfectly well. One
# witness per class of character is enough, since each class fails for a
# single shared reason.
NAME_PROBES = {
    "apostrophe": "'",
    "backslash": "\\",
    "control": "\t",
    "delete": "\x7F",
    "non-ascii": "é",
}

_name_verdicts = None


def _probe_names():
    """Measure which characters this engine really stores, and how it fails."""
    global _name_verdicts
    if _name_verdicts is not None:
        return _name_verdicts

    _name_verdicts = {}
    for cls, char in NAME_PROBES.items():
        witness = "A" + char + "B"
        try:
            field = bytes(PatchEncoder.encode_text(witness, NAME_BYTES))
        except Exception:  # noqa: BLE001 - the failure is the measurement
            _name_verdicts[cls] = "cannot be encoded"
            continue
        try:
            same = PatchBinary._qc_name(field) == witness
        except Exception:  # noqa: BLE001 - idem
            same = False
        _name_verdicts[cls] = None if same else "truncates the name when read back"
    return _name_verdicts


def _char_problem(c):
    """Return why this engine cannot store the character, or None."""
    verdicts = _probe_names()
    if ord(c) > 0x7F:
        return verdicts["non-ascii"]
    if ord(c) == 0x7F:
        return verdicts["delete"]
    if ord(c) < 0x20:
        return verdicts["control"]
    if c == "'":
        return verdicts["apostrophe"]
    if c == "\\":
        return verdicts["backslash"]
    return None

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


def _config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "claude-zoia-skill", "config.json")


def _load_config():
    try:
        with open(_config_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_config(cfg):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


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


def _parse_bin(path):
    """Read and parse a .bin, reporting a bad file instead of a traceback."""
    try:
        raw = _read_bin(path)
    except OSError as e:
        sys.stderr.write("error: cannot read {} ({}).\n".format(path, e.strerror))
        raise SystemExit(2)

    if len(raw) < 24:
        sys.stderr.write(
            "error: {} is {} bytes — too short to be a ZOIA patch "
            "(they are 32768).\n".format(path, len(raw))
        )
        raise SystemExit(2)

    try:
        return raw, PatchBinary().parse_data(raw)
    except Exception as e:  # noqa: BLE001 - any parse failure is a bad file
        sys.stderr.write(
            "error: {} could not be parsed as a ZOIA patch "
            "({}: {}).\n".format(path, type(e).__name__, e)
        )
        raise SystemExit(2)


def _write_bin(path, data):
    """Write a patch, leaving the target untouched if anything goes wrong."""
    tmp = path + ".partial"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


MODULE_HEADER_FIELDS = {
    0: "the module size",
    1: "the module type",
    2: "the module version",
    3: "the page number — pages above 63 (Euroburo I/O) are reset to 0",
    4: "the header colour",
    5: "the grid position",
    6: "the parameter count",
    7: "the saved-data size",
    8: "module options the module index does not describe",
    9: "module options the module index does not describe",
}


def _diff_causes(raw, encoded, patch):
    """Name the fields the re-encode would change, for a useful diagnosis."""
    differing = {i // 4 for i in range(min(len(raw), len(encoded))) if raw[i] != encoded[i]}
    if not differing:
        return []

    bounds, step = [], 6
    for m in patch.get("modules", []):
        size = m.get("size") or 0
        bounds.append((step, step + size))
        step += size

    causes = set()
    for word in differing:
        for start, end in bounds:
            if start <= word < end:
                offset = word - start
                causes.add(
                    MODULE_HEADER_FIELDS.get(offset, "module parameters or saved data")
                )
                break
        else:
            causes.add("the connections, pages, starred params or colours")
    return sorted(causes)


def _fidelity_problem(raw, patch, param_order="order"):
    """Say why this patch cannot be written back faithfully, or return None."""
    try:
        encoded = bytes(PatchEncoder().encode(patch, param_order_mode=param_order))
    except Exception as e:  # noqa: BLE001 - reported, not handled
        return "re-encoding it fails outright ({}: {})".format(type(e).__name__, e), []

    if encoded == raw:
        return None, []

    diff = sum(1 for a, b in zip(encoded, raw) if a != b)
    diff += abs(len(encoded) - len(raw))

    try:
        readable = PatchBinary().parse_data(encoded) == patch
    except Exception:  # noqa: BLE001 - the result simply does not parse
        readable = False

    summary = "re-encoding it changes {} bytes{}".format(
        diff, "" if readable else ", and the result no longer reads back the same"
    )
    return summary, _diff_causes(raw, encoded, patch)


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


def _check_names(patch):
    """Return [(where, name, problem)] for names the pedal cannot store.

    The parser reads names by string-splitting the repr() of their bytes, so an
    apostrophe or a non-ASCII character comes back truncated ("Don't Panic"
    reads back as "t Panic"), and the encoder raises struct.error on non-ASCII.
    """
    problems = []

    def listing(chars):
        return " ".join(repr(c) for c in sorted(chars))

    def check(where, name):
        if not isinstance(name, str):
            return

        reasons = []
        by_problem = {}
        for c in name:
            problem = _char_problem(c)
            if problem:
                by_problem.setdefault(problem, set()).add(c)
        for problem in sorted(by_problem):
            reasons.append("{}: {}".format(problem, listing(by_problem[problem])))
        if len(name.encode("utf-8", "replace")) > NAME_BYTES:
            reasons.append("longer than {} bytes".format(NAME_BYTES))

        if reasons:
            problems.append((where, name, "; ".join(reasons)))

    check("patch name", patch.get("name"))
    for m in patch.get("modules", []):
        check("module {}".format(m.get("number")), m.get("name"))
    for i, page in enumerate(patch.get("pages", [])):
        check("page {}".format(i), page)
    return problems


def _report_names(problems):
    sys.stderr.write(
        "error: {} name(s) the ZOIA cannot store.\n\n".format(len(problems))
    )
    width = max(len(w) for w, _, _ in problems)
    for where, name, why in problems:
        sys.stderr.write("  {:<{w}}  {!r:<20} {}\n".format(where, name, why, w=width))
    sys.stderr.write(
        "\nNames hold {} bytes. The characters above were measured against the\n"
        "engine in use, not assumed: a patched or newer zoia_lib accepts more\n"
        "of them than an unpatched one.\n"
        "Rename them, or pass --force to write the patch anyway.\n".format(NAME_BYTES)
    )


def cmd_decode(args):
    load_engine()
    in_path = _abs(args.input)
    raw, patch = _parse_bin(in_path)

    # Refuse before writing anything: a patch that cannot be rebuilt must not
    # become the starting point of an edit.
    problem, causes = _fidelity_problem(raw, patch)
    if problem:
        sys.stderr.write(
            "error: {} cannot be written back faithfully "
            "({}).\n\n".format(args.input, problem)
        )
        if causes:
            sys.stderr.write("What would change:\n")
            for cause in causes:
                sys.stderr.write("  - {}\n".format(cause))
            sys.stderr.write("\n")
        sys.stderr.write(
            "Writing this patch back would silently alter it, so decoding is\n"
            "refused. Re-saving the patch on the pedal usually converts it to a\n"
            "layout the encoder can rebuild.\n"
            "`info` and `roundtrip` still work on it.\n"
        )
        return 2

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

    problems = _check_names(patch)
    if problems:
        _report_names(problems)
        if not args.force:
            return 2
        sys.stderr.write("\n--force given, encoding anyway.\n\n")

    out_path = _abs(args.output) or (in_path.rsplit(".", 1)[0] + ".bin")
    try:
        data = PatchEncoder().encode(patch, param_order_mode=args.param_order)
    except struct.error as e:
        sys.stderr.write("error: the encoder could not write this patch ({}).\n".format(e))
        sys.stderr.write(
            "A non-ASCII character in a name is the usual cause: the encoder "
            "counts\ncharacters but writes bytes, so 'e' costs one and "
            "'é' costs two.\n"
        )
        return 1
    _write_bin(out_path, data)
    print("Encoded {} -> {} ({} bytes)".format(args.input, out_path, len(data)))
    return 0


def cmd_info(args):
    load_engine()
    _, patch = _parse_bin(_abs(args.input))
    print("\n".join(_summary_lines(patch)))
    return 0


def cmd_roundtrip(args):
    """Decode then re-encode a .bin and report how faithfully it reproduces."""
    load_engine()
    original, patch = _parse_bin(_abs(args.input))
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


def _sanitize(name):
    """Turn a patch name into the filename form the ZOIA uses on its card."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip())
    return cleaned.strip("_") or "patch"


def _slot_of(filename):
    m = SLOT_RE.match(filename)
    return int(m.group(1)) if m else None


def cmd_sd(args):
    """Register (or show) the ZOIA patch folder on the SD card."""
    cfg = _load_config()

    if not args.path:
        current = cfg.get("sd_path")
        if not current:
            print("No SD patch folder registered.")
            print("Register one with:")
            print("    patch_cli.py sd /Volumes/<CARD>/<zoia patch folder>")
            return 2
        print("SD patch folder: {}".format(current))
        if os.path.isdir(current):
            patches = sorted(f for f in os.listdir(current) if SLOT_RE.match(f))
            print("status:          mounted, {} patch(es)".format(len(patches)))
        else:
            print("status:          NOT AVAILABLE (card unmounted, or folder gone)")
        print("config:          {}".format(_config_path()))
        return 0

    path = os.path.abspath(_abs(args.path))
    if not os.path.isdir(path):
        sys.stderr.write("error: {} is not a directory.\n".format(path))
        sys.stderr.write(
            "Give the folder holding the patches, not the root of the card.\n"
        )
        return 2

    patches = [f for f in os.listdir(path) if SLOT_RE.match(f)]
    if not patches and not args.force:
        sys.stderr.write(
            "error: no <slot>_zoia_<name>.bin file in {}.\n".format(path)
        )
        sys.stderr.write(
            "This does not look like the ZOIA patch folder. Check the path, or\n"
            "re-run with --force to register it anyway.\n"
        )
        return 2

    cfg["sd_path"] = path
    _save_config(cfg)
    print("Registered SD patch folder: {}".format(path))
    print("{} patch(es) currently on the card.".format(len(patches)))
    print("Saved to {}".format(_config_path()))
    return 0


def cmd_sync(args):
    """Copy a .bin onto the registered SD patch folder, into its slot."""
    src = _abs(args.input)
    if not os.path.isfile(src):
        sys.stderr.write("error: {} does not exist.\n".format(src))
        return 2

    folder = _abs(args.folder) if args.folder else _load_config().get("sd_path")
    if not folder:
        sys.stderr.write(
            "error: no SD patch folder registered.\n"
            "Register it once with:  patch_cli.py sd /Volumes/<CARD>/<folder>\n"
        )
        return 2
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        sys.stderr.write(
            "error: {} is not available.\n"
            "Is the card mounted? Check with `patch_cli.py sd`.\n".format(folder)
        )
        return 2

    # Never put a file on the pedal that we cannot read back ourselves.
    load_engine()
    raw, patch = _parse_bin(src)

    base = os.path.basename(src)
    slot = args.slot if args.slot is not None else _slot_of(base)
    if slot is None:
        sys.stderr.write(
            "error: cannot tell which slot {} belongs to.\n"
            "Name it <slot>_zoia_<name>.bin, or pass --slot N.\n".format(base)
        )
        return 2
    if not 0 <= slot <= 63:
        sys.stderr.write("error: slot {} is outside 0-63.\n".format(slot))
        return 2

    occupying = sorted(f for f in os.listdir(folder) if _slot_of(f) == slot)

    if args.name:
        target = "{:03d}_zoia_{}.bin".format(slot, _sanitize(args.name))
    elif _slot_of(base) == slot:
        target = base
    elif occupying:
        # Keep whatever the slot is already called, so nothing has to be deleted.
        target = occupying[0]
    else:
        target = "{:03d}_zoia_{}.bin".format(slot, _sanitize(patch.get("name")))

    dest = os.path.join(folder, target)
    stale = [f for f in occupying if f != target]

    print("patch:   {} ({} modules)".format(patch.get("name"), len(patch.get("modules", []))))
    print("slot:    {:03d}".format(slot))
    print("target:  {}".format(dest))
    if os.path.exists(dest):
        print("         (overwrites the file already there)")
    for f in stale:
        print("removes: {}".format(os.path.join(folder, f)))

    if stale and not args.replace:
        sys.stdout.flush()
        sys.stderr.write(
            "\nerror: slot {:03d} is already taken by {}.\n".format(
                slot, ", ".join(stale)
            )
        )
        sys.stderr.write(
            "A slot holds one patch, so writing under a new name means deleting\n"
            "the old file. Re-run with --replace to do that, or drop --name to\n"
            "overwrite the existing file in place.\n"
        )
        return 2

    if args.dry_run:
        print("\ndry run - nothing written")
        return 0

    _write_bin(dest, raw)

    written = _read_bin(dest)
    if written != raw:
        sys.stderr.write(
            "error: {} does not match the source after copying.\n".format(dest)
        )
        return 1

    for f in stale:
        os.remove(os.path.join(folder, f))

    print("\nSynced and verified. Eject the card before unplugging it.")
    return 0


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
        choices=["order", "blocks"],
        help="parameter order used only when a module has no parameters_raw",
    )
    e.add_argument(
        "--force",
        action="store_true",
        help="encode even if a name uses characters the pedal cannot store",
    )
    e.set_defaults(func=cmd_encode)

    i = sub.add_parser("info", help="print a human-readable patch summary")
    i.add_argument("input", help="path to the .bin patch")
    i.set_defaults(func=cmd_info)

    r = sub.add_parser("roundtrip", help="check encoder fidelity for a .bin")
    r.add_argument("input", help="path to the .bin patch")
    r.add_argument("--param-order", default="order", choices=["order", "blocks"])
    r.add_argument("--max-ranges", type=int, default=20, help="diff ranges to show")
    r.set_defaults(func=cmd_roundtrip)

    sd = sub.add_parser(
        "sd", help="register (or show) the ZOIA patch folder on the SD card"
    )
    sd.add_argument(
        "path",
        nargs="?",
        help="folder holding the patches, e.g. /Volumes/CARD/ZOIA "
        "(not the root of the card). Omit to show the current setting.",
    )
    sd.add_argument(
        "--force",
        action="store_true",
        help="register even if no patch file is found there",
    )
    sd.set_defaults(func=cmd_sd)

    sy = sub.add_parser("sync", help="copy a .bin onto the SD card, into its slot")
    sy.add_argument("input", help="path to the .bin patch")
    sy.add_argument("--slot", type=int, help="target slot 0-63 (default: from filename)")
    sy.add_argument("--name", help="rename the patch on the card (needs --replace)")
    sy.add_argument(
        "--replace",
        action="store_true",
        help="delete the file already occupying the slot under another name",
    )
    sy.add_argument("--folder", help="write here instead of the registered folder")
    sy.add_argument("--dry-run", action="store_true", help="show what would happen")
    sy.set_defaults(func=cmd_sync)

    w = sub.add_parser("where", help="show which engine checkout is in use")
    w.set_defaults(func=cmd_where)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
