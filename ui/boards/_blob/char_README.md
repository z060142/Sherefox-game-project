# Character standees (char_<id>.png)

Placeholder art for the prototype; not final.

Generator: Image Summon (Codex CLI gpt-image), transparent-background full-body standees, 1024x1536 RGBA PNG.
The files here are the originals at full size (not trimmed, so the 2:3 frame and the figure's placement stay
exactly as before), re-encoded with ImageMagick `magick <original>.png -strip -define png:compression-level=9
-define png:compression-strategy=1 char_<id>.png` (lossless; metadata stripped).

The boards draw them in fixed logical boxes (`object-fit: contain`): vn `.ch-art` 440x660, debate opponent 300x450,
debate Sherefox 340x510, the Arthur avatar crops in investigate / board / debate / result. The 1024x1536 source is
sharp at 2x in every one of them.

| file | original (prompt "Full-body character standee ...") |
|---|---|
| char_sherefox.png | sherefox.png (Image Summon 20261105-190731) |
| char_arthur.png | arthur.png (20261105-232015) |
| char_baskerville.png | baskerville.png (20261105-190940) |
| char_victor.png | victor.png (20261105-190942) |
| char_wolfhart.png | wolfhart.png (20261105-190924) |
| char_valet.png | opp_valet.png (20261105-193600) |
| char_partner.png | opp_partner.png (20261105-193547) |

`art_masthead.png` (2172x724, title and paper masthead) is already the generator original (20261105-232229).
