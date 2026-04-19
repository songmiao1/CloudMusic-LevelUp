const fs = require('fs');
const path = require('path');
const https = require('https');

const target = path.join(
  __dirname,
  '..',
  'node_modules',
  '@neteasecloudmusicapienhanced',
  'api',
  'data',
  'china_ip_ranges.txt',
);

const source =
  'https://raw.githubusercontent.com/songmiao1/api-enhanced/main/data/china_ip_ranges.txt';

function ensureDirectory(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function download(url, destination) {
  return new Promise((resolve, reject) => {
    const request = https.get(url, (response) => {
      if (
        response.statusCode &&
        response.statusCode >= 300 &&
        response.statusCode < 400 &&
        response.headers.location
      ) {
        response.resume();
        download(response.headers.location, destination).then(resolve).catch(reject);
        return;
      }

      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`unexpected status ${response.statusCode}`));
        return;
      }

      const file = fs.createWriteStream(destination);
      response.pipe(file);
      file.on('finish', () => file.close(resolve));
      file.on('error', reject);
    });

    request.on('error', reject);
  });
}

async function main() {
  if (fs.existsSync(target)) {
    return;
  }

  ensureDirectory(target);

  try {
    await download(source, target);
    console.log('Downloaded china_ip_ranges.txt for api-enhanced.');
  } catch (error) {
    fs.writeFileSync(target, '', 'utf8');
    console.warn(
      `Unable to download china_ip_ranges.txt, created an empty fallback instead: ${error.message}`,
    );
  }
}

main().catch((error) => {
  console.warn(`postinstall fallback failed: ${error.message}`);
});
