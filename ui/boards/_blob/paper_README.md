# Newspaper front-page illustrations (paper_ch01 - paper_ch04)

Placeholder art generated for the prototype; not final.

Generator: Image Summon (Codex CLI gpt-image), 1536x1024 originals. Post-process (ImageMagick):
`magick in.png -colorspace gray -level 5%,95% +level-colors "#123a31","#f3eedf" -filter Lanczos -resize 960x -quality 88 out.jpg`

All files are 960x640 JPEG (quality 88), two-colour palette (ink green #123a31 on newsprint #f3eedf).

Common prompt prefix: "A Victorian newspaper wood engraving / steel engraving illustration, wide landscape 3:2 composition. Monochrome: only dark ink green (#123a31) fine lines on warm newsprint (#f3eedf) paper background, fine hatching and cross-hatching for shading, no other colours, no gradients, no text, no letters, no logos, no border, no frame."

| id | file | size | subject prompt (after the common prefix) |
|---|---|---|---|
| paper_ch01 | paper_ch01.jpg | 960x640 | Subject: steampunk-tinged Victorian London street, 1887, Baker Street. A long winding queue of gentlemen in top hats and ladies in bustle dresses waiting in front of a pastry shop shopfront window. In the window, clearly visible on a display stand, a caramel pudding topped with a brass clockwork gear mechanism. Near the front of the queue stands a fox-eared girl detective in a brown coat and deerstalker cap, anime light-novel character style rendered as engraving. Gas street lamps, cobblestones. |
| paper_ch02 | paper_ch02.jpg | 960x640 | Subject: the shop window of a Victorian clock shop in steampunk-tinged London, 1887. In the window a large cuckoo-style wall clock with a small carved bird mid-call emerging from its little door, small but readable, and the pendulum cover visible below the clock; many other clocks and gears on shelves; the dim shop interior glimpsed through the glass. (extra: no numerals on dials, no signage lettering) |
| paper_ch03 | paper_ch03.jpg | 960x640 | Subject: a steam barge moored on the River Thames at night in thick fog, smokestack and boiler. On the stone quay a line of police lanterns glowing in the fog, and at the lantern line the dark silhouette of a bowler-hatted dog-eared police inspector in a long uniform coat, anime light-novel style rendered as engraving. Moody, dense fog rendered with sparse hatching. |
| paper_ch04 | paper_ch04.jpg | 960x640 | Subject: the stage of the Royal Opera House, London 1887, just after an accident. A broken stage lift: a snapped piston rod and a tilted platform in the stage floor, steam rising. The opera cast in elaborate costumes scattering in alarm, and a fallen soprano in a grand gown being helped up by two people. Painted backdrop, curtains and a glimpse of the audience boxes. |
