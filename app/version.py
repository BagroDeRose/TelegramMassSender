"""Single source of truth for the application version shown in
Diagnostics (ROADMAP: Diagnostics). Bumped only when cutting an actual
release (see the v1.0.0-v1.3.0 git tags) -- an unreleased development
build correctly still reports the last released version, the same way
semantic versioning normally works between releases.
"""
APP_VERSION = "1.3.0"
