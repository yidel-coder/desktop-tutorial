# Outreach data

- `../bd_config.json` - who counts as a target (fit rules), who the email is from, and the pitch text.
- `../contacts.csv` - one row per employer: contact name, title, email, phone, website, where it came from, and
  status (`new`, `ready`, `sent`, `replied`, `meeting`, `not_interested`, `bounced`, `do_not_contact`).
  `employer` must match the employer name shown on the dashboard (case and punctuation are ignored).
- `outreach_<date>.csv` - written by `jobs_build.py`: every target with its contact and the generated subject and body,
  ready for a mail-merge or sequencing tool.

Only business contact details for facilities (administrator, director of nursing, HR) belong here.
