"""One email check for registration, login, invitations, and the admin command.

A reserved suffix such as .local is accepted. The create-admin command and
the login form have to agree, or an account created on the command line
cannot sign in.
"""
from __future__ import annotations


def normalize_email(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("A valid email address is required.")
    text = value.strip().lower()
    if text.count("@") != 1 or any(character.isspace() for character in text):
        raise ValueError("A valid email address is required.")
    local, domain = text.split("@")
    labels = domain.split(".")
    if not local or len(labels) < 2 or any(not label for label in labels):
        raise ValueError("A valid email address is required.")
    return text
