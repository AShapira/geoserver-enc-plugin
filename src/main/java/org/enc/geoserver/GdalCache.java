package org.enc.geoserver;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.logging.Logger;

/** Immutable cache generations. No shell, shared JNI state, or native handles in the JVM. */
final class GdalCache {
    private static final Logger LOG = Logger.getLogger(GdalCache.class.getName());
    private static final String RECIPE = recipe();
    private static String recipe() {
        try (var stream = GdalCache.class.getResourceAsStream("cache-recipe.txt")) {
            if (stream == null) throw new IOException("Missing cache recipe resource");
            return new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8).strip();
        } catch (IOException e) { throw new ExceptionInInitializerError(e); }
    }

    static List<Path> exchangeFiles(Path base) throws IOException {
        base = base.toRealPath();
        String name = base.getFileName().toString();
        if (!Files.isRegularFile(base) || !name.toLowerCase(Locale.ROOT).endsWith(".000"))
            throw new IOException("S-57 source must be a local .000 base cell");
        String stem = name.substring(0, name.length() - 4);
        try (var files = Files.list(base.getParent())) {
            return files.filter(Files::isRegularFile).filter(p -> {
                String n = p.getFileName().toString();
                return n.length() == stem.length() + 4 && n.startsWith(stem + ".")
                    && n.substring(n.length() - 3).matches("[0-9]{3}");
            }).sorted().toList();
        }
    }

    static String fingerprint(Path base, String version) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update((RECIPE + "\n" + version + "\n" + base.toRealPath()).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            for (Path p : exchangeFiles(base)) {
                digest.update(p.getFileName().toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
                try (var in = Files.newInputStream(p)) {
                    byte[] buffer = new byte[65536];
                    int count;
                    while ((count = in.read(buffer)) != -1) digest.update(buffer, 0, count);
                }
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException e) { throw new AssertionError(e); }
    }

    static String run(List<String> command, Path log, int timeout) throws IOException {
        Process process = new ProcessBuilder(command).redirectErrorStream(true).redirectOutput(log.toFile()).start();
        try {
            if (!process.waitFor(timeout, TimeUnit.SECONDS)) {
                process.destroyForcibly();
                process.waitFor();
                throw new IOException("GDAL timed out after " + timeout + " seconds");
            }
            String output;
            try (var input = Files.newInputStream(log)) {
                output = new String(input.readNBytes(32768), java.nio.charset.StandardCharsets.UTF_8);
            }
            if (process.exitValue() != 0) throw new IOException("GDAL failed (" + process.exitValue() + "): " + output);
            // Some driver update errors are emitted despite a successful ogr2ogr exit.
            if (output.matches("(?s).*ERROR [0-9]+:.*")) throw new IOException("GDAL reported an error: " + output);
            return output.strip();
        } catch (InterruptedException e) {
            process.destroyForcibly();
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted waiting for GDAL", e);
        }
    }

    static void validateAppliedUpdates(Path base, Path snapshot) throws IOException {
        int expected = exchangeFiles(base).stream().mapToInt(p -> Integer.parseInt(
            p.getFileName().toString().substring(p.getFileName().toString().length() - 3))).max().orElse(0);
        try (var connection = DriverManager.getConnection("jdbc:sqlite:" + snapshot);
             var statement = connection.createStatement();
             var rows = statement.executeQuery("SELECT DSID_UPDN, DSID_EDTN FROM DSID")) {
            if (!rows.next()) throw new IOException("GDAL snapshot has no DSID record");
            int actual = Integer.parseInt(rows.getString(1));
            if ("0".equals(rows.getString(2))) throw new IOException("ENC is cancelled (edition 0)");
            // Reissued base files may already contain updates: with no sidecars, UPDN may be > 0.
            if (expected > 0 && expected != actual)
                throw new IOException("Incomplete ENC update chain: highest sidecar is " + expected + ", GDAL applied " + actual);
        } catch (SQLException | NumberFormatException e) {
            throw new IOException("Cannot verify S-57 update sequence in GDAL snapshot", e);
        }
    }

    static synchronized Path materialize(Path base, Path directory, String executable, int timeout) throws IOException {
        base = base.toRealPath();
        exchangeFiles(base);
        Files.createDirectories(directory);
        Path log = Files.createTempFile(directory, "gdal-", ".log");
        try {
            String version = run(List.of(executable, "--version"), log, timeout);
            String key = fingerprint(base, version);
            Path result = directory.resolve(key + ".gpkg");
            try (var channel = FileChannel.open(directory.resolve(key + ".lock"), StandardOpenOption.CREATE, StandardOpenOption.WRITE);
                 var lock = channel.lock()) {
                if (Files.isRegularFile(result)) return result;
                Path scratch = Files.createTempDirectory(directory, "import-");
                Path temporary = scratch.resolve("chart.gpkg");
                try {
                    String output = run(List.of(executable, "-f", "GPKG", temporary.toString(), base.toString(),
                        "-oo", "UPDATES=APPLY", "-oo", "SPLIT_MULTIPOINT=ON", "-oo", "ADD_SOUNDG_DEPTH=ON",
                        "-oo", "LNAM_REFS=ON", "-oo", "LIST_AS_STRING=ON", "-unsetFid", "-unsetFieldWidth",
                        "-mapFieldType", "StringList=String,IntegerList=String",
                        "-lco", "SPATIAL_INDEX=YES"), log, timeout);
                    if (!key.equals(fingerprint(base, version))) throw new IOException("ENC changed during import; retry with a stable exchange set");
                    if (!Files.isRegularFile(temporary) || Files.size(temporary) == 0) throw new IOException("GDAL produced no GeoPackage");
                    validateAppliedUpdates(base, temporary);
                    Files.move(temporary, result, StandardCopyOption.ATOMIC_MOVE);
                    LOG.info("S-57 snapshot " + base.getFileName() + " -> " + key + " (" + version + ")");
                    if (!output.isEmpty()) LOG.warning(output);
                    return result;
                } finally {
                    try (var leftovers = Files.list(scratch)) {
                        for (Path p : leftovers.toList()) Files.deleteIfExists(p);
                    }
                    Files.deleteIfExists(scratch);
                }
            }
        } finally { Files.deleteIfExists(log); }
    }
}
