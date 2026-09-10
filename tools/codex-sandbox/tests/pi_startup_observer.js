import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';

export default function (pi) {
  pi.on('session_start', () => {
    const { requests } = JSON.parse(readFileSync(new URL('./observer-workload.json', import.meta.url), 'utf8'));
    async function exerciseProxy() {
      for (let i = 0; i < requests; i++) {
        await new Promise((resolve, reject) => {
          const child = spawn('jj', ['status'], { stdio: 'ignore' });
          child.on('error', reject);
          child.on('exit', (code, signal) => code === 0 ? resolve() : reject(new Error(`jj exited ${code ?? signal}`)));
        });
      }
      process.stderr.write('__SANDBOX_PROXY_WORK_DONE__');
    }
    let input = '';
    process.stdin.on('data', data => {
      input = (input + Buffer.from(data).toString()).slice(-64);
      if (input.includes('nft-key-probe')) {
        process.stderr.write('__SANDBOX_PI_KEY__');
      }
    });
    process.stderr.write('__SANDBOX_PI_READY__');
    exerciseProxy().catch(error => process.stderr.write(`__SANDBOX_PROXY_WORK_FAILED__ ${error.message}`));
  });
}
