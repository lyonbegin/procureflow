# TinyFish live browser recovery tests — 2026-10-22

This document records actual UI-level tests, not Railway-deployed crawler results. Tests opened one real detail item per site. A TinyFish run does not by itself prove a continuous backend worker is functioning.

| Source | Real page/record verified | Result | TinyFish run |
|---|---|---|---|
| Wishket project | https://www.wishket.com/project/159077/ | Public metadata yes; detailed requirements behind login | https://agent.tinyfish.ai/runs/bf5a1a4f-3087-4c19-b180-b77343c24d65 |
| Wishket portfolio | https://www.wishket.com/partners/wishket-portfolio/314603/ | Visible client/stack and partial scope; contract terms gated | https://agent.tinyfish.ai/runs/161f401a-a65a-4cbe-bdd7-1c185fd302cb |
| Wishket partner | https://www.wishket.com/partners/p/fourdpocket/ | Redirects to Wishket authentication | https://agent.tinyfish.ai/runs/161f401a-a65a-4cbe-bdd7-1c185fd302cb |
| Wanted Gigs | https://www.wanted.co.kr/gigs/projects/14718 | Old gigs.wanted.co.kr returns ERR_EMPTY_RESPONSE; new listing route works; full detail login-gated | https://agent.tinyfish.ai/runs/9beec985-2d18-4232-a5ad-fa038a70faef |
| K-apt | https://www.k-apt.go.kr/bid/bidList.do | Public list and bid detail confirmed: kg2b_142446 | https://agent.tinyfish.ai/runs/eb26f01b-a913-40a3-9940-16c0383ac78c |
| G2B / 나라장터 | https://www.g2b.go.kr/ | Public sitemap -> 발주 -> 발주목록 -> row detail works: R26DD20905075 | https://agent.tinyfish.ai/runs/e75fd944-28b6-45ac-a194-289634085cce |

## Corrections to previous assumptions

- A first G2B browser attempt failed to expand the top menu and guessed authentication was required. A second actual browser run proved **G2B public order list and detail accessible without login** through the sitemap.
- K-apt and G2B navigation success means their old headless failures cannot be classified as authentication failures.
- Wishket and Wanted Gigs detailed fields do require their respective authenticated sessions. A Freemoa login does not authenticate these unrelated sites.
- The Wanted legacy host is broken, but its newer /gigs/projects site is active.

## Code fixes committed

- `market_probe.py`: Wanted Gigs probe corrected to https://www.wanted.co.kr/gigs/projects
- `legacy/g2b_prod_nav.py`: additional sitemap fallback when WebSquare top-level navigation fails.
- `tests/test_g2b_sitemap.py` and `.github/workflows/g2b-navigation.yml`: safe URL and sitemap fallback tests.

## Unfinished portions

- Login-verified Wishket and Wanted full detail collection require separate authorized profiles.
- Existing ProcureFlow Railway worker has **not** been confirmed deployed by these browser tests.
- Repeated/bulk collection and live database insertion have **not** been measured by these TinyFish one-detail probes.
