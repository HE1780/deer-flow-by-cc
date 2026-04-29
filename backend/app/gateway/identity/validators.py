"""Shared validators for the identity subsystem."""

import re

# Pragmatic email regex — RFC 5322 is too permissive for our needs and we
# don't want to drag in `email-validator`. Tightened during onboarding flow.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
