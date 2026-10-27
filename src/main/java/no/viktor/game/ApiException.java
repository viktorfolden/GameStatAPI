package no.viktor.game;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

class ApiException extends ResponseStatusException {
    ApiException(HttpStatus status, String reason) {
        super(status, reason);
    }
}
