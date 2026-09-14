COLOR CARDS FIX 48
- Fixed /my-stuff/color-card/save for NOT NULL stuff_cards.created_at.
- Save endpoint now records created_at on new cards and updated_at on every save.
- Fixed mobile PNG action to use the server attachment download directly; avoids unreliable PWA blob downloads.
- Existing cards/data preserved.
