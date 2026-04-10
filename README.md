# FrictionBot — MuxBot for TheFrictionRealm

Telegram bot deployed on Hugging Face Spaces (Docker).  
Muxes .ass subtitles into video, converts/styles .srt, and serves large files as leech links.

## Features
- **Fast downloads** — Pyrogram multi-worker parallel downloads (10+ MB/s on HF)
- **2-hour video cache** — same video is not downloaded twice within 2 hours
- **Leech server** — files >2 GB are served via HTTP link instead of Telegram upload
- **Subtitle styling** — apply Cinematic or Full 4K ASS header to any .srt
- **Subtitle convert** — SRT ↔ ASS conversion
- **Mux mode** — embed .ass into .mkv losslessly via FFmpeg

## Environment Variables (HF Secrets)
| Variable | Description |
|---|---|
| `API_ID` | Telegram API ID |
| `API_HASH` | Telegram API Hash |
| `BOT_TOKEN` | Bot token from @BotFather |
| `PUBLIC_URL` | Your HF Space URL, e.g. `https://frictionx7-frictionbot.hf.space` |

## Commands
| Command | Description |
|---|---|
| `/mux` | Mux a subtitle into a video |
| `/style` | Apply ASS style header to .srt |
| `/convert` | Convert between SRT and ASS |
| `/speed` | Test HF server speed |
| `/cache` | View video cache status |

## Leech Links
Files >2 GB after muxing are moved to the leech server and a direct download link is sent.  
Links expire after **2 hours**.  
Set `PUBLIC_URL` to your HF Space URL so links work externally.
