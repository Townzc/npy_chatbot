"""Identity mapping lives in DataService's atomic import transaction.

No nickname or exporter-owner inference is permitted. A Persona's confirmed
source account + sender ID maps to its target_identity_id; use policy and
human-origin confirmation are per Persona and never overwrite raw source IDs.
"""
