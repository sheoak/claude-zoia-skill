The `.bin` files in this repo are Empress ZOIA patches, edited with the
zoia-patch-edit skill: https://github.com/sheoak/claude-zoia-skill

The skill is declared in `.claude/settings.json`. Its engine is cloned once per
machine into `~/.cache/claude-zoia-skill/`; run `patch_cli.py setup` if a patch
command reports it is missing.
