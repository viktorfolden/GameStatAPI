package no.viktor.game;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JOSEObjectType;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.ECDSASigner;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jose.jwk.Curve;
import com.nimbusds.jose.jwk.ECKey;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.gen.ECKeyGenerator;
import com.nimbusds.jose.jwk.gen.RSAKeyGenerator;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Testcontainers
class GameApiIntegrationTest {
    @Container
    static final PostgreSQLContainer<?> DATABASE = new PostgreSQLContainer<>("postgres:17-alpine")
            .withInitScript("init-roles.sql");

    static final RSAKey SIGNING_KEY;
    static final ECKey EC_SIGNING_KEY;
    static final HttpServer JWKS_SERVER;
    static final String ISSUER;

    static {
        try {
            SIGNING_KEY = new RSAKeyGenerator(2048).keyID("test-rsa").generate();
            EC_SIGNING_KEY = new ECKeyGenerator(Curve.P_256).keyID("test-ec").generate();
            JWKS_SERVER = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            byte[] jwks = new JWKSet(List.of(SIGNING_KEY.toPublicJWK(), EC_SIGNING_KEY.toPublicJWK()))
                    .toString().getBytes(StandardCharsets.UTF_8);
            JWKS_SERVER.createContext("/auth/v1/.well-known/jwks.json", exchange -> {
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, jwks.length);
                try (var body = exchange.getResponseBody()) {
                    body.write(jwks);
                }
            });
            JWKS_SERVER.start();
            ISSUER = "http://127.0.0.1:" + JWKS_SERVER.getAddress().getPort() + "/auth/v1";
        } catch (IOException | JOSEException exception) {
            throw new ExceptionInInitializerError(exception);
        }
    }

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", DATABASE::getJdbcUrl);
        registry.add("spring.datasource.username", DATABASE::getUsername);
        registry.add("spring.datasource.password", DATABASE::getPassword);
        registry.add("supabase.issuer", () -> ISSUER);
    }

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @Autowired JdbcTemplate jdbc;

    @BeforeEach
    void clearRuns() {
        jdbc.execute("TRUNCATE game.runs, game.players");
        jdbc.update("DELETE FROM game.leaderboards WHERE id <> 'default'");
        jdbc.update("UPDATE game.leaderboards SET accepting_runs = TRUE");
    }

    @AfterAll
    static void stopJwksServer() {
        JWKS_SERVER.stop(0);
    }

    @Test
    void onlyHealthIsPublic() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk());
        mvc.perform(get("/v1/me/stats")).andExpect(status().isUnauthorized());
        mvc.perform(get("/v1/leaderboards/default")).andExpect(status().isUnauthorized());
        mvc.perform(post("/v1/runs").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/v1/me/stats").header("Authorization", "Bearer invalid"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void verifiesSignatureIssuerAudienceExpiryRoleAndSubject() throws Exception {
        UUID player = UUID.randomUUID();
        List<JWTClaimsSet> invalidClaims = List.of(
                claims(player).issuer("https://wrong.example/auth/v1").build(),
                claims(player).audience("wrong").build(),
                claims(player).audience(List.of()).build(),
                claims(player).claim("aud", null).build(),
                claims(player).expirationTime(Date.from(Instant.now().minusSeconds(120))).build(),
                claims(player).expirationTime(null).build(),
                claims(player).notBeforeTime(Date.from(Instant.now().plusSeconds(120))).build(),
                claims(player).claim("role", "service_role").build(),
                claims(player).claim("role", null).build(),
                claims(player).subject("not-a-uuid").build(),
                claims(player).subject(null).build());
        for (JWTClaimsSet invalid : invalidClaims) {
            mvc.perform(get("/v1/me/stats").header("Authorization", sign(invalid, SIGNING_KEY)))
                    .andExpect(status().isUnauthorized());
        }
        RSAKey attackerKey = new RSAKeyGenerator(2048).keyID(SIGNING_KEY.getKeyID()).generate();
        mvc.perform(get("/v1/me/stats")
                        .header("Authorization", sign(claims(player).build(), attackerKey)))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void acceptsRsaAndEcSupabaseSigningKeys() throws Exception {
        UUID player = UUID.randomUUID();
        mvc.perform(get("/v1/me/stats").header("Authorization", token(player)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.playerId").value(player.toString()))
                .andExpect(jsonPath("$.runsPlayed").value(0))
                .andExpect(jsonPath("$.accuracyPercent").value(nullValue()));

        SignedJWT ecJwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.ES256)
                .keyID(EC_SIGNING_KEY.getKeyID()).type(JOSEObjectType.JWT).build(), claims(player).build());
        ecJwt.sign(new ECDSASigner(EC_SIGNING_KEY));
        mvc.perform(get("/v1/me/stats").header("Authorization", "Bearer " + ecJwt.serialize()))
                .andExpect(status().isOk());
    }

    @Test
    void persistsRoundsAndComputesWeightedLifetimeStatistics() throws Exception {
        UUID player = UUID.randomUUID();
        submit(player, round(UUID.randomUUID(), "default", 100, 8, 2, 3, 60))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.submittedAt").isString());
        submit(player, round(UUID.randomUUID(), "default", 250, 1, 1, 2, 30))
                .andExpect(status().isCreated());
        submit(UUID.randomUUID(), round(UUID.randomUUID(), "default", 999, 100, 0, 100, 999))
                .andExpect(status().isCreated());

        mvc.perform(get("/v1/me/stats").header("Authorization", token(player)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.runsPlayed").value(2))
                .andExpect(jsonPath("$.bestScore").value(250))
                .andExpect(jsonPath("$.hits").value(9))
                .andExpect(jsonPath("$.misses").value(3))
                .andExpect(jsonPath("$.enemiesKilled").value(5))
                .andExpect(jsonPath("$.playTimeSeconds").value(90))
                .andExpect(jsonPath("$.accuracyPercent").value(75.0));
    }

    @Test
    void retriesDoNotDoubleCountAndConflictsCannotOverwriteOrStealRounds() throws Exception {
        UUID player = UUID.randomUUID();
        UUID runId = UUID.randomUUID();
        var original = round(runId, "default", 100, 8, 2, 3, 60);
        String stored = submit(player, original).andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        submit(player, original).andExpect(status().isOk())
                .andExpect(result -> assertThat(result.getResponse().getContentAsString()).isEqualTo(stored));
        submit(player, round(runId, "default", 200, 8, 2, 3, 60)).andExpect(status().isConflict());
        submit(UUID.randomUUID(), original).andExpect(status().isConflict());

        jdbc.update("UPDATE game.leaderboards SET accepting_runs = FALSE");
        submit(player, original).andExpect(status().isOk());
        submit(player, round(UUID.randomUUID(), "default", 100, 8, 2, 3, 60))
                .andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM game.runs", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM game.players", Long.class)).isEqualTo(1);
    }

    @Test
    void simultaneousRetriesCreateExactlyOneRound() throws Exception {
        UUID player = UUID.randomUUID();
        var round = round(UUID.randomUUID(), "default", 100, 1, 0, 1, 10);
        List<Callable<Integer>> submissions = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            submissions.add(() -> submit(player, round).andReturn().getResponse().getStatus());
        }
        try (var executor = Executors.newFixedThreadPool(6)) {
            List<Integer> statuses = new ArrayList<>();
            for (var result : executor.invokeAll(submissions)) {
                statuses.add(result.get());
            }
            assertThat(statuses).containsOnly(200, 201);
            assertThat(statuses.stream().filter(code -> code == 201).count()).isEqualTo(1);
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM game.runs", Long.class)).isEqualTo(1);
    }

    @Test
    void rejectsNegativeMissingFractionalAndUnknownInput() throws Exception {
        UUID player = UUID.randomUUID();
        var valid = round(UUID.randomUUID(), "default", 100, 1, 0, 1, 10);
        for (String field : List.of("score", "hits", "misses", "enemiesKilled", "playTimeSeconds")) {
            var negative = json.valueToTree(valid);
            ((com.fasterxml.jackson.databind.node.ObjectNode) negative).put(field, -1);
            submit(player, negative).andExpect(status().isBadRequest());
            var fractional = json.valueToTree(valid);
            ((com.fasterxml.jackson.databind.node.ObjectNode) fractional).put(field, 1.5);
            submit(player, fractional).andExpect(status().isBadRequest());
        }
        submit(player, Map.of()).andExpect(status().isBadRequest());
        var spoofed = json.valueToTree(valid);
        ((com.fasterxml.jackson.databind.node.ObjectNode) spoofed).put("playerId", UUID.randomUUID().toString());
        submit(player, spoofed).andExpect(status().isBadRequest());
        var stringScore = json.valueToTree(valid);
        ((com.fasterxml.jackson.databind.node.ObjectNode) stringScore).put("score", "100");
        submit(player, stringScore).andExpect(status().isBadRequest());
        submit(player, round(UUID.randomUUID(), "missing", 100, 1, 0, 1, 10))
                .andExpect(status().isNotFound());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM game.runs", Long.class)).isZero();
    }

    @Test
    void statsArePrivateUnlessThePlayerOptsIn() throws Exception {
        UUID player = UUID.randomUUID();
        UUID other = UUID.randomUUID();
        submit(player, round(UUID.randomUUID(), "default", 100, 1, 0, 1, 10))
                .andExpect(status().isCreated());
        mvc.perform(get("/v1/me/profile").header("Authorization", token(player)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.shareStats").value(false));
        mvc.perform(get("/v1/players/" + player + "/stats").header("Authorization", token(other)))
                .andExpect(status().isNotFound());
        mvc.perform(get("/v1/players/" + player + "/stats").header("Authorization", token(player)))
                .andExpect(status().isOk());
        mvc.perform(patch("/v1/me/profile").header("Authorization", token(player))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(new ApiModels.ProfileRequest("Viktor", true))))
                .andExpect(status().isOk()).andExpect(jsonPath("$.displayName").value("Viktor"));
        mvc.perform(get("/v1/players/" + player + "/stats").header("Authorization", token(other)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.hits").value(1));
        mvc.perform(patch("/v1/me/profile").header("Authorization", token(player))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(new ApiModels.ProfileRequest("Viktor", false))))
                .andExpect(status().isOk());
        mvc.perform(get("/v1/players/" + player + "/stats").header("Authorization", token(other)))
                .andExpect(status().isNotFound());
        mvc.perform(patch("/v1/me/profile").header("Authorization", token(player))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"displayName\":\" \",\"shareStats\":true}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void leaderboardsUseBestScoresTiedRanksAndSeparateBoards() throws Exception {
        jdbc.update("""
                INSERT INTO game.leaderboards (id, name, game_version, game_mode, difficulty, season)
                VALUES ('hard', 'Hard', '1', 'standard', 'hard', 'all-time')
                """);
        UUID first = UUID.fromString("00000000-0000-0000-0000-000000000001");
        UUID tied = UUID.fromString("00000000-0000-0000-0000-000000000002");
        UUID third = UUID.randomUUID();
        submit(first, round(UUID.randomUUID(), "default", 500, 0, 0, 0, 0)).andExpect(status().isCreated());
        submit(first, round(UUID.randomUUID(), "default", 100, 0, 0, 0, 0)).andExpect(status().isCreated());
        submit(tied, round(UUID.randomUUID(), "default", 500, 0, 0, 0, 0)).andExpect(status().isCreated());
        submit(third, round(UUID.randomUUID(), "default", 200, 0, 0, 0, 0)).andExpect(status().isCreated());
        submit(third, round(UUID.randomUUID(), "hard", 900, 0, 0, 0, 0)).andExpect(status().isCreated());
        mvc.perform(get("/v1/leaderboards").header("Authorization", token(first)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.length()").value(2));
        mvc.perform(get("/v1/leaderboards/default").header("Authorization", token(first)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.entries.length()").value(3))
                .andExpect(jsonPath("$.entries[0].playerId").value(first.toString()))
                .andExpect(jsonPath("$.entries[0].score").value(500))
                .andExpect(jsonPath("$.entries[0].rank").value(1))
                .andExpect(jsonPath("$.entries[1].rank").value(1))
                .andExpect(jsonPath("$.entries[2].rank").value(3));
        mvc.perform(get("/v1/leaderboards/default?limit=1&offset=2").header("Authorization", token(first)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.entries.length()").value(1))
                .andExpect(jsonPath("$.entries[0].playerId").value(third.toString()));
        mvc.perform(get("/v1/leaderboards/default/me").header("Authorization", token(third)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.player.rank").value(3))
                .andExpect(jsonPath("$.neighbors.length()").value(3));
        mvc.perform(get("/v1/leaderboards/default/me").header("Authorization", token(UUID.randomUUID())))
                .andExpect(status().isOk()).andExpect(jsonPath("$.player").value(nullValue()))
                .andExpect(jsonPath("$.neighbors.length()").value(0));
        for (String query : List.of("?limit=0", "?limit=101", "?offset=-1", "?offset=10001")) {
            mvc.perform(get("/v1/leaderboards/default" + query).header("Authorization", token(first)))
                    .andExpect(status().isBadRequest());
        }
        mvc.perform(get("/v1/leaderboards/missing").header("Authorization", token(first)))
                .andExpect(status().isNotFound());
    }

    @Test
    void aggregatesBeyondIntegerRangeAndKeepsDatabasePrivate() throws Exception {
        UUID player = UUID.randomUUID();
        for (int i = 0; i < 2; i++) {
            submit(player, round(UUID.randomUUID(), "default", Long.MAX_VALUE,
                    Integer.MAX_VALUE, Integer.MAX_VALUE, Integer.MAX_VALUE, Integer.MAX_VALUE))
                    .andExpect(status().isCreated());
        }
        mvc.perform(get("/v1/me/stats").header("Authorization", token(player)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.hits").value(4294967294L))
                .andExpect(jsonPath("$.playTimeSeconds").value(4294967294L))
                .andExpect(jsonPath("$.accuracyPercent").value(50.0));
        for (String role : List.of("anon", "authenticated")) {
            assertThat(jdbc.queryForObject("SELECT has_schema_privilege(?, 'game', 'USAGE')",
                    Boolean.class, role)).isFalse();
        }
        assertThat(jdbc.queryForObject("""
                SELECT COUNT(*) FROM pg_tables
                WHERE schemaname = 'game' AND tablename IN ('players', 'runs', 'leaderboards')
                    AND rowsecurity
                """, Long.class)).isEqualTo(3);
    }

    private ResultActions submit(UUID player, Object round) throws Exception {
        return mvc.perform(post("/v1/runs").header("Authorization", token(player))
                .contentType(MediaType.APPLICATION_JSON).content(json.writeValueAsString(round)));
    }

    private ApiModels.RunRequest round(UUID id, String board, long score, int hits,
                                      int misses, int enemies, int seconds) {
        return new ApiModels.RunRequest(id, board, score, hits, misses, enemies, seconds);
    }

    private String token(UUID player) throws JOSEException {
        return sign(claims(player).build(), SIGNING_KEY);
    }

    private JWTClaimsSet.Builder claims(UUID player) {
        return new JWTClaimsSet.Builder().subject(player.toString()).issuer(ISSUER)
                .audience("authenticated").claim("role", "authenticated")
                .issueTime(Date.from(Instant.now().minusSeconds(10)))
                .expirationTime(Date.from(Instant.now().plusSeconds(3600)));
    }

    private String sign(JWTClaimsSet claims, RSAKey key) throws JOSEException {
        SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256)
                .keyID(key.getKeyID()).type(JOSEObjectType.JWT).build(), claims);
        jwt.sign(new RSASSASigner(key));
        return "Bearer " + jwt.serialize();
    }
}
