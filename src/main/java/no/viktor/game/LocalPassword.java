package no.viktor.game;

import java.io.Console;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;

import javax.crypto.AEADBadTagException;
import javax.crypto.Cipher;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

final class LocalPassword {
    private static final byte[] HEADER = "VIKTPW01".getBytes(StandardCharsets.US_ASCII);
    private static final int SALT_SIZE = 16;
    private static final int NONCE_SIZE = 12;
    private static final int MAX_FILE_SIZE = 4096;
    private static final int ITERATIONS = 600_000;

    record Startup(boolean encryptOnly, String password, String[] args) {}

    private LocalPassword() {}

    static Startup prepare(String[] args) throws IOException, GeneralSecurityException {
        List<String> remaining = new ArrayList<>();
        Path file = null;
        boolean encryptOnly = false;
        for (int i = 0; i < args.length; i++) {
            if (args[i].equals("--encrypt-local-password") || args[i].equals("--local-password-file")) {
                if (file != null || i + 1 == args.length || args[i + 1].startsWith("--")) {
                    throw new IllegalArgumentException("Specify exactly one local password option followed by a file path");
                }
                encryptOnly = args[i].equals("--encrypt-local-password");
                file = Path.of(args[++i]);
            } else {
                remaining.add(args[i]);
            }
        }
        if (file == null) {
            return new Startup(false, null, args);
        }
        if (encryptOnly && !remaining.isEmpty()) {
            throw new IllegalArgumentException("Encryption mode does not accept server arguments");
        }
        Console console = System.console();
        if (console == null) {
            throw new IllegalStateException("Local password mode needs an interactive terminal. Run java -jar directly.");
        }
        char[] master = readPassword(console, "Master password: ");
        try {
            if (encryptOnly) {
                if (master.length < 16) {
                    throw new IllegalArgumentException("Use a strong master passphrase of at least 16 characters");
                }
                char[] confirmation = readPassword(console, "Confirm master password: ");
                try {
                    if (!Arrays.equals(master, confirmation)) {
                        throw new IllegalArgumentException("Master passwords do not match");
                    }
                } finally {
                    Arrays.fill(confirmation, '\0');
                }
                char[] databasePassword = readPassword(console, "Supabase database password: ");
                try {
                    writeNewFile(file, encrypt(databasePassword, master));
                } finally {
                    Arrays.fill(databasePassword, '\0');
                }
                console.printf("Encrypted password saved. Keep the master passphrase separate from this file.%n");
                return new Startup(true, null, new String[0]);
            }
            byte[] encrypted;
            try (var input = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
                encrypted = input.readNBytes(MAX_FILE_SIZE + 1);
            }
            return new Startup(false, decrypt(encrypted, master), remaining.toArray(String[]::new));
        } finally {
            Arrays.fill(master, '\0');
        }
    }

    private static char[] readPassword(Console console, String prompt) {
        char[] password = console.readPassword("%s", prompt);
        if (password == null || password.length == 0) {
            throw new IllegalArgumentException("Password entry cancelled or empty");
        }
        return password;
    }

    static byte[] encrypt(char[] password, char[] master) throws GeneralSecurityException {
        byte[] plaintext = new String(password).getBytes(StandardCharsets.UTF_8);
        try {
            if (plaintext.length == 0 || plaintext.length > MAX_FILE_SIZE - HEADER.length - SALT_SIZE - NONCE_SIZE - 16) {
                throw new IllegalArgumentException("Database password is empty or too long");
            }
            SecureRandom random = new SecureRandom();
            byte[] salt = new byte[SALT_SIZE];
            byte[] nonce = new byte[NONCE_SIZE];
            random.nextBytes(salt);
            random.nextBytes(nonce);
            Cipher cipher = cipher(Cipher.ENCRYPT_MODE, master, salt, nonce);
            byte[] ciphertext = cipher.doFinal(plaintext);
            return ByteBuffer.allocate(HEADER.length + salt.length + nonce.length + ciphertext.length)
                    .put(HEADER).put(salt).put(nonce).put(ciphertext).array();
        } finally {
            Arrays.fill(plaintext, (byte) 0);
        }
    }

    static String decrypt(byte[] data, char[] master) throws GeneralSecurityException {
        if (data.length < HEADER.length + SALT_SIZE + NONCE_SIZE + 17 || data.length > MAX_FILE_SIZE) {
            throw new IllegalArgumentException("Invalid encrypted password file size");
        }
        ByteBuffer buffer = ByteBuffer.wrap(data);
        byte[] header = new byte[HEADER.length];
        byte[] salt = new byte[SALT_SIZE];
        byte[] nonce = new byte[NONCE_SIZE];
        buffer.get(header).get(salt).get(nonce);
        if (!Arrays.equals(header, HEADER)) {
            throw new IllegalArgumentException("Unsupported encrypted password file format");
        }
        byte[] ciphertext = new byte[buffer.remaining()];
        buffer.get(ciphertext);
        byte[] plaintext;
        try {
            plaintext = cipher(Cipher.DECRYPT_MODE, master, salt, nonce).doFinal(ciphertext);
        } catch (AEADBadTagException exception) {
            throw new GeneralSecurityException("Wrong master password or damaged encrypted password file", exception);
        }
        try {
            return new String(plaintext, StandardCharsets.UTF_8);
        } finally {
            Arrays.fill(plaintext, (byte) 0);
        }
    }

    private static Cipher cipher(int mode, char[] master, byte[] salt, byte[] nonce)
            throws GeneralSecurityException {
        PBEKeySpec spec = new PBEKeySpec(master, salt, ITERATIONS, 256);
        byte[] key = null;
        try {
            key = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(mode, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, nonce));
            cipher.updateAAD(HEADER);
            return cipher;
        } finally {
            spec.clearPassword();
            if (key != null) {
                Arrays.fill(key, (byte) 0);
            }
        }
    }

    static void writeNewFile(Path file, byte[] data) throws IOException {
        boolean posix = Files.getFileStore(file.toAbsolutePath().getParent())
                .supportsFileAttributeView("posix");
        // Create-only prevents accidental replacement; POSIX permissions apply atomically.
        var attributes = posix
                ? new java.nio.file.attribute.FileAttribute<?>[] {
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))}
                : new java.nio.file.attribute.FileAttribute<?>[0];
        try (FileChannel channel = FileChannel.open(file,
                Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE), attributes)) {
            ByteBuffer buffer = ByteBuffer.wrap(data);
            while (buffer.hasRemaining()) {
                channel.write(buffer);
            }
        }
    }
}
