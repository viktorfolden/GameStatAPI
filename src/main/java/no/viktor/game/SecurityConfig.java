package no.viktor.game;

import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
class SecurityConfig {
    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        return http
                // This API accepts bearer tokens only, never cookie-based authentication.
                .csrf(csrf -> csrf.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.GET, "/health").permitAll()
                        .anyRequest().authenticated())
                .oauth2ResourceServer(resource -> resource.jwt(jwt -> {}))
                .build();
    }

    @Bean
    NimbusJwtDecoder jwtDecoder(@Value("${supabase.issuer}") String issuer,
                               @Value("${supabase.audience}") String audience) {
        NimbusJwtDecoder decoder = NimbusJwtDecoder
                .withJwkSetUri(issuer + "/.well-known/jwks.json")
                .jwsAlgorithm(SignatureAlgorithm.ES256)
                .jwsAlgorithm(SignatureAlgorithm.RS256)
                .build();
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                JwtValidators.createDefaultWithIssuer(issuer), playerClaimsValidator(audience)));
        return decoder;
    }

    private OAuth2TokenValidator<Jwt> playerClaimsValidator(String audience) {
        return jwt -> {
            boolean validSubject = false;
            if (jwt.getSubject() != null) {
                try {
                    validSubject = UUID.fromString(jwt.getSubject()).toString()
                            .equalsIgnoreCase(jwt.getSubject());
                } catch (IllegalArgumentException ignored) {
                    // A non-UUID subject is not a Supabase player account.
                }
            }
            if (!validSubject || jwt.getExpiresAt() == null
                    || jwt.getAudience() == null || !jwt.getAudience().contains(audience)
                    || !"authenticated".equals(jwt.getClaimAsString("role"))) {
                return OAuth2TokenValidatorResult.failure(
                        new OAuth2Error("invalid_token", "Invalid player token claims", null));
            }
            return OAuth2TokenValidatorResult.success();
        };
    }
}
