# The Rural Update private podcast feed

The Rural Update publishes a private RSS feed for direct subscription in podcast apps.

Feed URL:

https://6nywfpnnw8-wq.github.io/The-Rural-Update/podcast.xml

## Apple Podcasts

On iPhone or iPad:

1. Open Apple Podcasts.
2. Open Library.
3. Tap the More (...) menu.
4. Choose **Follow a Show by URL**.
5. Paste the feed URL above.
6. Tap **Follow**.

The feed is intentionally marked with `<itunes:block>Yes</itunes:block>` so it is not intended for public Apple Podcasts directory discovery.

## Daily publication flow

1. The 6:00 AM Rural Update task creates `podcast-script/YYYY-MM-DD.txt`.
2. GitHub Actions generates `audio/YYYY-MM-DD.mp3`.
3. The feed generator rebuilds `podcast.xml` from all complete dated script/audio pairs.
4. GitHub Pages publishes the updated feed and media.
5. Podcast apps following the feed can retrieve the new episode.

## Feed assets

- Show feed: `podcast.xml`
- Show artwork: `podcast-art.png`
- Episode audio: `audio/YYYY-MM-DD.mp3`
- Source scripts: `podcast-script/YYYY-MM-DD.txt`

Episode GUIDs are date-based and stable so later metadata changes do not create duplicate episodes.
