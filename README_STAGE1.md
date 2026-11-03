# SmartBook AI — Stage 1 Contact Validation Patch

Target: `ritik-exelance-it/Smartbook_AI`, `master` as inspected.

## Apply
1. Back up or commit your current project.
2. Copy all four files from this ZIP into the repository root.
3. Run `python apply_stage1_patch.py` from the repository root.
4. Activate your virtual environment and run `pip install -r requirements.txt`.
5. Run `python -m unittest discover -s tests -v`.
6. Run `python -m unittest test_contact_validation -v`.

The script creates `.stage1.bak` backups for modified files and stops if its exact source matches do not match the inspected version. Do not force it if it stops.

## Changes
- Adds a shared email/phone validation module.
- Normalizes email whitespace and domain casing.
- Validates phone numbers using `phonenumbers`; stores them in E.164 format.
- Uses the same checks during escalation intake and before database persistence.
- Preserves optional contact details and existing Slack consent behavior.
- Does not modify booking or cancellation logic.

This validates syntax and phone numbering-plan validity; it does not verify ownership. OTP/confirmation would be a separate feature.
