package no.viktor.game;

import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.GeneralSecurityException;
import java.util.Arrays;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import static org.assertj.core.api.Assertions.*;

class LocalPasswordTest {
    @TempDir Path directory;

    @Test
    void roundTripUsesFreshSaltAndNonce() throws Exception {
        char[] password = "database-password-\u00e6".toCharArray();
        char[] master = "a long master passphrase".toCharArray();
        byte[] first = LocalPassword.encrypt(password, master);
        byte[] second = LocalPassword.encrypt(password, master);
        assertThat(first).isNotEqualTo(second);
        assertThat(LocalPassword.decrypt(first, master)).isEqualTo(new String(password));
        assertThat(LocalPassword.decrypt(second, master)).isEqualTo(new String(password));
    }

    @Test
    void wrongMasterAndTamperingFailClosed() throws Exception {
        char[] master = "a long master passphrase".toCharArray();
        byte[] encrypted = LocalPassword.encrypt("database-password".toCharArray(), master);
        assertThatThrownBy(() -> LocalPassword.decrypt(encrypted, "wrong passphrase".toCharArray()))
                .isInstanceOf(GeneralSecurityException.class);
        for (int position : new int[] {8, 24, encrypted.length - 1}) {
            byte[] corrupted = encrypted.clone();
            corrupted[position] ^= 1;
            assertThatThrownBy(() -> LocalPassword.decrypt(corrupted, master))
                    .isInstanceOf(GeneralSecurityException.class);
        }
        byte[] header = encrypted.clone();
        header[0] ^= 1;
        assertThatThrownBy(() -> LocalPassword.decrypt(header, master))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> LocalPassword.decrypt(Arrays.copyOf(encrypted, 20), master))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> LocalPassword.decrypt(new byte[4097], master))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void createsPrivateFileAndRefusesToOverwrite() throws Exception {
        Path file = directory.resolve("supabase.enc");
        byte[] encrypted = LocalPassword.encrypt("database-password".toCharArray(),
                "a long master passphrase".toCharArray());
        LocalPassword.writeNewFile(file, encrypted);
        assertThat(Files.readAllBytes(file)).isEqualTo(encrypted);
        if (Files.getFileStore(directory).supportsFileAttributeView("posix")) {
            assertThat(Files.getPosixFilePermissions(file))
                    .isEqualTo(PosixFilePermissions.fromString("rw-------"));
        }
        assertThatThrownBy(() -> LocalPassword.writeNewFile(file, new byte[] {1}))
                .isInstanceOf(FileAlreadyExistsException.class);
        assertThat(Files.readAllBytes(file)).isEqualTo(encrypted);
    }

    @Test
    void normalStartupIsUnchangedAndInvalidOptionsFail() throws Exception {
        String[] args = {"--server.port=9090"};
        var startup = LocalPassword.prepare(args);
        assertThat(startup.encryptOnly()).isFalse();
        assertThat(startup.password()).isNull();
        assertThat(startup.args()).isEqualTo(args);
        assertThatThrownBy(() -> LocalPassword.prepare(new String[] {"--local-password-file"}))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> LocalPassword.prepare(new String[] {
                "--encrypt-local-password", "file", "--server.port=9090"}))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> LocalPassword.prepare(new String[] {
                "--local-password-file", "one", "--local-password-file", "two"}))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
