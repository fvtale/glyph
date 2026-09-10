# Approved listings, one per file

Each `.json` file here is one listing that a person approved, named by its `id`.
The board builder reads every file in this directory alongside `../curated.json`.

Files normally arrive through a pull request opened by the listing intake: a
venue emails its dates, the receptionist in datarail-agents drafts them onto a
`listings/*` branch, and `.github/workflows/listing-intake.yml` checks them with
`feed/intake.py` and opens the PR. Merging it is the approval.

One file per listing, rather than appending to one shared array, means two
submissions merged on the same day can never conflict. It also makes clearing
out the past a matter of deleting files.

A listing here that has already happened is not an error. CI checks these for
shape only, and the board drops anything in the past by itself.
