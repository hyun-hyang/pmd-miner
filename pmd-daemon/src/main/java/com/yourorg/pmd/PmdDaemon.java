package com.yourorg.pmd;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import net.sourceforge.pmd.PMDConfiguration;
import net.sourceforge.pmd.PmdAnalysis;
import net.sourceforge.pmd.lang.LanguageVersion;
import net.sourceforge.pmd.lang.java.JavaLanguageModule;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

public class PmdDaemon {
    public static void main(String[] args) throws IOException {

        String host = "0.0.0.0";
        int port = 8000;
        String cachePath = null;
        boolean ignoreErrors = false;

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--listen":
                    host = args[++i];
                    break;
                case "--port":
                    port = Integer.parseInt(args[++i]);
                    break;
                case "--cache":
                    cachePath = args[++i];
                    break;
                case "--ignore-errors":
                    ignoreErrors = true;
                    break;
                default:
            }
        }
        final String _cachePath = cachePath;
        final boolean _ignoreErrors = ignoreErrors;

        // 1) 포트 설정 및 HTTP 서버 생성
        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        ObjectMapper mapper = new ObjectMapper();

        server.createContext("/analyze", (HttpExchange exchange) -> {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                exchange.sendResponseHeaders(405, -1); // Method Not Allowed
                return;
            }
            // 2) 요청 본문에서 JSON 파싱
            TypeReference<Map<String, Object>> typeRef = new TypeReference<>() {};
            Map<String, Object> reqMap = mapper.readValue(exchange.getRequestBody(), typeRef);
            String path = (String) reqMap.get("path");
            String ruleset = (String) reqMap.get("ruleset");
            String auxCP = (String) reqMap.getOrDefault("auxClasspath", "");

            // 변경된 파일 리스트 (증분분석용)
            @SuppressWarnings("unchecked")
            List<String> files = (List<String>) reqMap.get("files");

            // 3) PMD 설정
            PMDConfiguration configuration = new PMDConfiguration();
            configuration.setDefaultLanguageVersion(JavaLanguageModule.getInstance().getLatestVersion());

            if (files != null && !files.isEmpty()) {
                // 증분분석: 전달된 상대경로 목록만 분석
                for (String rel : files) {
                    Path filePath = Path.of(path).resolve(rel);
                    if (Files.exists(filePath)) {
                        configuration.addInputPath(filePath);
                    }
                }
            } else {
                configuration.addInputPath(Path.of(path));
            }
            configuration.addRuleSet(ruleset);
            configuration.setReportFormat("json");
            Path reportFile = Path.of(path, "pmd-report.json");
            configuration.setReportFile(reportFile);


            // 캐시 사용
            if (_cachePath != null) {
                configuration.setAnalysisCacheLocation(_cachePath);
                // 캐시 파싱 에러 무시
                if (_ignoreErrors) {
                    configuration.setIgnoreIncrementalAnalysis(true);
                }
            }

            // 추가 클래스패스
            if (!auxCP.isBlank()) {
                configuration.prependAuxClasspath(auxCP);
            }


            // 4) 분석 실행
            try (PmdAnalysis analysis = PmdAnalysis.create(configuration)) {
                analysis.performAnalysis();
            } catch (Exception e) {
                String err = e.toString() + "\n" +
                        java.util.Arrays.stream(e.getStackTrace())
                                .map(Object::toString)
                                .collect(Collectors.joining("\n"));
                byte[] b = ("{ \"error\": \"" + err.replace("\"","\\\"") + "\" }").getBytes();
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(500, b.length);
                try (OutputStream os = exchange.getResponseBody()) {
                    os.write(b);
                }
                return;
            }

            // 5) 결과 파일 읽어 응답
            byte[] responseBody = Files.readAllBytes(reportFile);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, responseBody.length);
            try (OutputStream os = exchange.getResponseBody()) {
                os.write(responseBody);
            }
        });

        System.out.printf("PMD Daemon listening on http://%s:%d/analyze%n", host, port);
        server.start();
    }
}
