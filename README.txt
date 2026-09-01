THE RURAL UPDATE
Home Screen Web App Package

FILES
- index.html: main dashboard
- manifest.webmanifest: web app metadata
- sw.js: service worker for app shell/offline fallback
- icons/apple-touch-icon.png: iPhone/iPad Home Screen icon
- icons/icon-192.png: PWA icon
- icons/icon-512.png: PWA icon
- icons/icon-maskable-512.png: maskable PWA icon
- the-rural-update-logo.png: full brand lockup supplied by the user

IMPORTANT
This package must be served from an HTTPS website for full PWA/service-worker behavior. Opening index.html directly from Files will not provide the complete web-app experience.

INSTALL ON IPHONE
1. Upload this entire folder to an HTTPS web host, preserving the folder structure.
2. Open the hosted index.html page in Safari on iPhone.
3. Tap Share.
4. Tap Add to Home Screen.
5. Turn on Open as Web App if iOS presents the option.
6. Confirm the name The Rural Update and tap Add.

ARCHIVE
The existing index.html contains relative links to dated archive folders. Copy those folders beside index.html on the host if you want those links to work.

UPDATES
When replacing the dashboard each morning, preserve manifest.webmanifest, sw.js, icons/, and the archive folder structure. If you materially change cached assets, increment the CACHE version in sw.js.
