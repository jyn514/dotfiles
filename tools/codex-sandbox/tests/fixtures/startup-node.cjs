process.stderr.write('Startup boundary: Node preload\n');

if (process.env.PI_STARTUP_PROFILE && !process.env.PI_STARTUP_PROFILE_OWNER) {
    process.env.PI_STARTUP_PROFILE_OWNER = String(process.pid);
    const fs = require('node:fs');
    const inspector = require('node:inspector');
    const session = new inspector.Session();
    session.connect();
    session.post('Profiler.enable');
    session.post('Profiler.start');
    const started = process.hrtime.bigint();
    const cpu = process.cpuUsage();
    let readiness;
    const write = process.stderr.write;
    process.stderr.write = function (chunk, ...args) {
        if (!readiness && String(chunk).includes('interactiveMode.init:')) {
            readiness = {elapsed: Number(process.hrtime.bigint() - started) / 1e9,
                         cpu: process.cpuUsage(cpu)};
        }
        return write.call(this, chunk, ...args);
    };
    process.on('exit', () => {
        const timing = {readiness, exit: {elapsed: Number(process.hrtime.bigint() - started) / 1e9,
                                         cpu: process.cpuUsage(cpu)}};
        session.post('Profiler.stop', (error, result) => {
            if (error) throw error;
            fs.writeFileSync(`/startup-output/node-${process.pid}.cpuprofile`, JSON.stringify(result.profile));
            fs.writeFileSync(`/startup-output/node-${process.pid}-time.json`, JSON.stringify(timing));
        });
        session.disconnect();
    });
}
