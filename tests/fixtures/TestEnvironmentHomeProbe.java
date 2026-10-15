import java.nio.file.Files;
import java.nio.file.Path;

class TestEnvironmentHomeProbe {
    public static void main(String[] args) throws Exception {
        String home = System.getenv("HOME");
        String propertyHome = System.getProperty("user.home");
        // Do not write anywhere unless isolation already holds.
        if (!home.equals(propertyHome)) {
            throw new IllegalStateException("user.home escaped the private HOME: " + propertyHome);
        }
        if (!"kept".equals(System.getProperty("test.existing.option"))) {
            throw new IllegalStateException("inherited Java option was lost");
        }
        Files.writeString(Path.of(propertyHome, "java-home-probe"), "private test state");
        System.out.println(home);
    }
}
