package no.viktor.game;

import java.util.Map;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class GameApiApplication {
    public static void main(String[] args) throws Exception {
        LocalPassword.Startup startup = LocalPassword.prepare(args);
        if (startup.encryptOnly()) {
            return;
        }
        SpringApplication application = new SpringApplication(GameApiApplication.class);
        if (startup.password() != null) {
            application.setDefaultProperties(Map.of("DATABASE_PASSWORD", startup.password()));
        }
        application.run(startup.args());
    }
}
