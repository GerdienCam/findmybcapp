# findmybc.app

Describe the problem. Find the Business Central apps that solve it.

findmybc.app is an independent, non-commercial finder for Business Central apps on the Microsoft Marketplace. You describe what's slow, manual or broken in your own words, answer up to five quick questions, and get a short list of apps whose listings say they handle it, with what each listing doesn't mention.

Not affiliated with or endorsed by Microsoft.

## How it works

- Every app is described from its own Microsoft Marketplace listing, in our own words, with a link to the listing. No listing text is copied.
- Apps are grouped by the business process need they solve, not by category.
- Results are ranked by how many of your answers a listing mentions, then by how much the listing describes. There are no paid rankings.
- The catalog is refreshed every month.
- Matching runs in your browser. Nothing you type is sent to us.

## For publishers

The best way to be found is a clear Marketplace listing: what your app does, for which countries and languages, and what it works with.

You can also add facts your listing doesn't carry. Each app has a file at `publisher-data/<publisher>/<app id>.json`. Open a pull request that changes it:

| Field | What it means |
| --- | --- |
| `countries` | Extra countries the app supports, ISO 3166-1 alpha-2, e.g. `NO` |
| `languages` | Extra UI languages, ISO 639-1, e.g. `nb`, `de-CH` |
| `extends` | Marketplace IDs of apps this app is an extension of |
| `worksWellWith` | Marketplace IDs of apps it is known to work well alongside |
| `showLogo`, `logoUrl` | Consent to show your logo, and an https link to it |

Every value feeds matching, so every value must be checkable. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Found something wrong?

Open an issue. Say which app, what the site shows, and what the listing actually says.

## Licence

The code and data are published so you can read them and learn from them. They are not open source: all rights are reserved. See [LICENSE](LICENSE).
