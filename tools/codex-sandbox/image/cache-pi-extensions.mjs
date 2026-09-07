import { readdirSync } from "node:fs";
import {
    DefaultPackageManager,
    DefaultResourceLoader,
    SettingsManager,
} from "/opt/agent-pi/src/packages/coding-agent/dist/bundle/index.js";

// Use the image's neutral build workspace; extension source paths remain stable under agentDir.
const cwd = "/workspace";
const agentDir = "/home/codex/.pi/agent";
const settingsManager = SettingsManager.create(cwd, agentDir);
const packages = new DefaultPackageManager({ cwd, agentDir, settingsManager });
const sources = settingsManager.getPackages().map(entry => typeof entry === "string" ? entry : entry.source);

switch (process.argv[2]) {
    case "install": {
        for (const source of sources) {
            console.log(`Installing cache input: ${source}`);
            await packages.install(source);
        }
        break;
    }
    case "warm": {
        // Offline resolution otherwise silently skips absent packages.
        for (const source of sources) {
            if (!packages.getInstalledPath(source, "user")) throw new Error(`Missing cache input: ${source}`);
        }
        // Load factories, but never create a session or send a model request.
        // Docker runs this phase without network access and discards its agent state.
        const loader = new DefaultResourceLoader({
            cwd, agentDir, settingsManager,
            noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
        });
        await loader.reload();
        const { extensions, errors } = loader.getExtensions();
        if (errors.length) throw new Error(JSON.stringify(errors));
        const files = readdirSync("/tmp/jiti");
        if (!extensions.length || !files.length) throw new Error("Pi extension cache is empty");
        console.log(`Cached ${extensions.length} extensions in ${files.length} files`);
        break;
    }
    default:
        throw new Error("Expected install or warm");
}
