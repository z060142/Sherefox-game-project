# Calligraphy cut-ins and stamps (01-systems 4.7, 00-overview "big-character table")

Placeholder art for the prototype; not final.

All files are transparent PNG, sized for 2x rendering (the boards draw cut-ins in a 900x430 `contain` box
and stamps in a 168x168 box, scaled up to 1.45x / 1.9x during the slam). Generated images: Image Summon (Codex
gpt-image) on a flat white (or black for stamp_seen) background, keyed to alpha (alpha = darkness over white, or
brightness over black, after a 6/255 paper-noise floor; colour un-premultiplied), trimmed at alpha > 2%, and the
stamps fitted to 640 px (Lanczos on premultiplied colour); PNG re-encoded losslessly with metadata stripped.
The four sample cut-ins are the transparent originals at full size.

| File | Word | Size (px) | Source |
|------|------|-----------|--------|
| cut_ronpa.png | 論破 | 1752x897 | sample cutin_ronpa.png (Image Summon 20261105-212054), full size |
| cut_hachiku.png | 破竹 | 1672x941 | sample cutin_pozhu.png (20261105-212532), full size |
| cut_konju.png | 困獸 | 1774x887 | sample cutin_kunshou.png (20261105-212209), full size |
| cut_shisshu.png | 失守 | 1774x887 | sample cutin_shishou.png (20261105-212321), full size |
| cut_shaken.png | 動搖 | 1730x838 | generated (20261106-020212, 1774x887), keyed and trimmed. Prompt: heavy black sumi-ink brush calligraphy of 動搖, trembling jittery ink edges, characters slightly tilted, gold-leaf flecks, small brass gear with steam, white background |
| stamp_parry.png | 截 | 640x638 | generated (20261106-020156, 1254x1254). Prompt: vermilion-red square seal (朱印方章) with the character 截, worn edges, white background |
| stamp_trap.png | 中計 | 615x640 | generated (20261106-020203). Prompt: black square seal with 中計 (中 above 計), stamped askew about 15 degrees, white background |
| stamp_whiff.png | 落空 | 631x640 | generated (20261106-020232). Prompt: hollow outline seal (白文) with 落空 in seal script, white background; recoloured to pale grey-brown ink #5a5650 at 66% opacity |
| stamp_clash.png | 交鋒 | 640x622 | generated (20261106-020512; the earlier side-by-side attempt 20261106-020243 is unused). Prompt: two square seals crossed in an X sharing one centre, red seal with 交 and black seal with 鋒, white background |
| stamp_seen.png | 看穿 | 640x603 | generated (20261106-020343). Prompt: metallic gold brush calligraphy 看穿 with a fox-tail shaped brush flourish, black background keyed out |
| stamp_assist.png | 援護 | 640x630 | generated (20261106-020339). Prompt: copper-brown gear-shaped seal with 援護 in carved seal style, white background |
| stamp_lost.png | 斷 | 640x636 | generated (20261106-020323). Prompt: small black square seal with 斷, recoloured to pale grey-brown ink #5a5650 at 52% opacity |
