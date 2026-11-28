# Media and metadata sources

Where `fetch-media` and `fetch-meta` get game media and tags, and how to choose
them with `--source` (or `default_metadata_source`).

| Source | `--source` | Needs | Gives |
|---|---|---|---|
| ScreenScraper | `screenscraper` | A user login and an issued developer ID (Setup) | Wheel logos, box art, screenshots, videos, themes, sounds, tags. The only source of videos and themes; a daily allowance per user |
| TheGamesDB | `thegamesdb` | An API key | Logos, box art, screenshots, banners, tags. About a thousand requests a month per key |
| LaunchBox Games Database | `launchbox` | `spindoctor launchbox-db update --apply` once (about 100 MB) | Clear logos, box art, screenshots, title screens, fanart; year, developer, genre, rating, players. Lookups are local |
| libretro-thumbnails | `libretro` | Nothing | Box art, screenshots and title screens for every system; logos for some. Matched by No-Intro / Redump file name; no tags |
| Steam store | `fetch-steam-media` | Nothing | Videos, screenshots, backgrounds and header art for PC games, one game at a time |

`auto` (the default) uses ScreenScraper and TheGamesDB as configured; `both`
asks ScreenScraper and fills its gaps from TheGamesDB.

## Several sources in turn

A comma list asks the sources in that order, each filling what the ones before it
lack:

```text
spindoctor fetch-media --system "Nintendo DS" --types wheel --source launchbox,thegamesdb
spindoctor config set default_metadata_source launchbox,thegamesdb
```

- The first source whose best match clears `match_threshold` supplies the game.
  A later source fills empty media slots and tags only when its own match clears
  it too, so a poor match never adds the wrong game's logo.
- In `fetch-media`, sources after the first that has every type a game is missing
  aren't asked for that game. Put sources with a monthly allowance last: they are
  used only for what the others don't have.
- `fetch-meta` asks every source in the list.

## LaunchBox Games Database

LaunchBox publishes its whole games database as one `Metadata.zip`, rebuilt daily,
with no account or key. SpinDoctor keeps a copy and an index of it in
`~/.spindoctor/launchbox`, and only the images `fetch-media --apply` downloads go
over the network.

```text
spindoctor launchbox-db update
spindoctor launchbox-db update --apply
spindoctor launchbox-db status
```

`update` says what it would download; `--apply` downloads only when LaunchBox has
published a newer file (`--force` always), then rebuilds the index (a minute or two).

- **Wheels and platforms:** a wheel named like a LaunchBox platform ("Nintendo DS",
  "Sega Genesis") needs nothing. SpinDoctor knows common other names, for example
  "Nintendo Famicom" (Nintendo Entertainment System, then Famicom Disk System) and
  "Sony Playstation Minis" (Sony PSP Minis, then Sony PSP). Set your own, in order:
  `spindoctor config system set "My Wheel" --launchbox-platform "Sony PSP"`.
- **Names:** a game matches on its title without region tags, punctuation, accents or
  a trailing ", The", or on one of LaunchBox's alternate names; otherwise on the
  closest title above `match_threshold`. LaunchBox lists arcade games by title, not
  by MAME set name, so MAME-style wheels rarely match.
- **Images:** Clear Logo → wheel, Box - Front → artwork, Screenshot - Gameplay → snap,
  Screenshot - Game Title → title, Fanart - Background → background. The ROM's
  region picks the image region (USA → North America, then World). LaunchBox has no
  videos or themes HyperSpin can use.

## libretro-thumbnails

The libretro project keeps thumbnails for every game in No-Intro / Redump naming,
one GitHub repository per system (`github.com/libretro-thumbnails`), with no key or
allowance. `thumbnails.libretro.com` serves the same files but answers 404, so
SpinDoctor takes them from `raw.githubusercontent.com`.

```text
spindoctor fetch-media --system "Nintendo DS" --types artwork,snap,title --source libretro
spindoctor fetch-media --system "Nintendo DS" --types wheel --source launchbox,libretro,thegamesdb
```

- **Folders:** Named_Logos → wheel, Named_Boxarts → artwork, Named_Snaps → snap,
  Named_Titles → title. Many systems have no Named_Logos folder (the DS hasn't),
  so libretro mostly fills box art and screenshots.
- **Wheels:** SpinDoctor knows the repositories for common wheel names, then tries
  "<Maker>_-_<Rest>" ("Atari Jaguar" → `Atari_-_Jaguar`). Set your own, in order:
  `spindoctor config system set "My Wheel" --libretro-system "Nintendo - Nintendo DS"`.
- **Names:** the game's own file name first (libretro writes `&*/:` and similar
  characters as `_`), then the same title with other tags (the closest tags win),
  then the closest title above `match_threshold`. Arcade sets named by MAME short
  name (`pacman`) don't match.
- **Requests:** one GitHub API call per system lists its files, saved in
  `~/.spindoctor/libretro` for `metadata_cache_ttl_days`. GitHub allows 60 such calls
  an hour without an account; when the list isn't available (or, like MAME's, is
  too big for one call), exact file names are checked one request each instead.
