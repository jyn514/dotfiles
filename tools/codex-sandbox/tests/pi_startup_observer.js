export default function (pi) {
  pi.on('session_start', () => {
    let input = '';
    process.stdin.on('data', data => {
      input = (input + Buffer.from(data).toString()).slice(-64);
      if (input.includes('nft-key-probe')) {
        process.stderr.write('__SANDBOX_PI_KEY__');
      }
    });
    process.stderr.write('__SANDBOX_PI_READY__');
  });
}
