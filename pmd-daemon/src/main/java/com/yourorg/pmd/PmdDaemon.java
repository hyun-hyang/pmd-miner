package com.yourorg.pmd;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import java.util.List;
import net.sourceforge.pmd.PMDConfiguration;
import net.sourceforge.pmd.PmdAnalysis;


import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import com.fasterxml.jackson.core.type.TypeReference;

public class PmdDaemon {
    public static void main(String[] args) throws IOException {

        // 1) 포트 설정 및 HTTP 서버 생성
        int port = 8000;
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
            if (files != null && !files.isEmpty()) {
                // 증분분석: 전달된 상대경로 목록만 분석
                for (String rel : files) {
                    Path filePath = Path.of(path).resolve(rel);
                    if (Files.exists(filePath)) {
                        configuration.addInputPath(filePath);
                    }
                }
            } else {
                // 전체 분석 (기존 동작)
                configuration.addInputPath(Path.of(path));
            }
            configuration.addRuleSet(ruleset);
            configuration.setReportFormat("json");
            Path reportFile = Path.of(path, "pmd-report.json");
            configuration.setReportFile(reportFile);  // ← takes a java.nio.file.Path
            if (auxCP != null && !auxCP.isBlank()) {
                configuration.prependAuxClasspath(auxCP);
            }

            // 4) 분석 실행
            try (PmdAnalysis analysis = PmdAnalysis.create(configuration)) {
                analysis.performAnalysis();
            } catch (Exception e) {
                String errMsg = "{ \"error\": \"" + e.getMessage().replace("\"", "\\\"") + "\" }";
                byte[] errBytes = errMsg.getBytes();
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(500, errBytes.length);
                try (OutputStream os = exchange.getResponseBody()) {
                    os.write(errBytes);
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

        System.out.println("PMD Daemon listening on http://localhost:" + port + "/analyze");
        server.start();
    }
}
