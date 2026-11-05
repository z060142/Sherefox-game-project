# Background placeholders (Ch.1-3 prototype)

Placeholder art generated for the prototype; not final.

Generator: Image Summon (Codex CLI gpt-image), no reference images, 1 attempt per id. Files were generated at 1672x941 and are now 1280x720 PNG.

The files live flat in `_blob/` as `bg_<id>.png`: xtframe-import reads a blob id as one file name (`/_blob/<file>`), never a sub-path.

Common prompt prefix: "Visual novel background illustration, wide 16:9 landscape, warm painterly thick-paint (impasto digital oil) style, fantasy steampunk Victorian London 1887." Common suffix: "Composition: clear open middle ground where character sprites will stand; the lower third of the image is calm, simple floor with low detail. No people, no characters, no text, no letters, no logos, no watermark, no frame. Clean game background art." Palette hints used: lamp gold #e0a050, copper #a65432, ink green #123a31, fog-night blue #1f2c3d.

| id | file | size | scene prompt (between prefix and suffix) |
| --- | --- | --- | --- |
| office_night | office_night.png | 1672x941 | Interior of a detective agency living room at night, Baker Street. Green banker's lamp and gas wall lamps, wood paneling, brass fittings. Steam radiator with brass pipes and pressure gauge, brass speaking tube, mechanic's workbench corner with prosthetic arm parts and tools, two leather armchairs, tall bookshelves, large window with foggy blue London night and gas lamp halos. |
| office_day | office_day.png | 1672x941 | Same living room by grey overcast morning daylight: soft cool grey light through the large window with misty street, a few still-glowing brass lamps; same props (radiator, speaking tube, workbench with prosthetic parts, armchairs, bookshelves). |
| kitchen_morning | kitchen_morning.png | 1672x941 | Small detective agency kitchen-cum-living-room corner in the morning, soft warm sunlight and gas lamp glow. Victorian wooden icebox with brass fittings and small brass dial, wooden table with one empty dessert plate, polished wooden floor, closed bedroom door at the side, copper pots. |
| clockshop | clockshop.png | 1672x941 | Interior of the Time Bird clock shop. Large ornate cuckoo-style bird clock with brass pendulum cover and carved bird, wooden counters, parts cabinets with many small drawers, shelves of clocks and gears, small corner coffee table with two chairs, warm gas lamp glow. |
| dock_fog | dock_fog.png | 1672x941 | Thames river dock in dense fog at night near dawn. Wet dark planks, mooring ropes and bollards, moored steam barge with brass funnel in the fog, gas lamps with golden halos, faint police lantern glow, cold fog-night blue dominant. |
| barge_deck | barge_deck.png | 1672x941 | Deck of a steam barge on the Thames in fog at night. Brass pressure valve wheel on a pipe, coiled ropes, wooden lectern-style logbook stand with a closed book, coal dust on wet deck planks, funnel and cabin wall, hanging lantern, cold blue mist. |
| boiler_room | boiler_room.png | 1672x941 | Cramped boiler room inside a steam barge. Riveted iron boiler with brass fittings, pressure release valve and gauges, heavy riveted iron door with a steam-driven latch bolt, stacked cargo crates, wisps of steam, dim red-orange furnace glow, copper pipes. |
| debate | debate.png | 1672x941 | Abstract stylized debate backdrop, low detail: Victorian newspaper-print / engraved steel-plate look, cream newsprint (#f3eedf, #e3d9c2) with halftone dots and column lines in ink green, copper pipes along the edges, large faint pressure-gauge dial motif in the centre-back, soft lamp-gold glow, vignette. (Suffix differs: no legible text.) |

Notes: the generator chooses the output size (cannot be set); native 1672x941 is 16:9 and larger than 1280x720, so scale down in the pipeline if needed. The debate backdrop contains small engraving vignettes (dome, steamship, train, chimneys) in the four corner/side areas and lamps at the top corners.
