package com.tianchuang.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.config.PythonServiceProperties;
import com.tianchuang.config.QweatherProperties;
import com.tianchuang.model.ForecastHour;
import com.tianchuang.model.WeatherSnapshot;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class PythonClient {

    private static final Logger log = LoggerFactory.getLogger(PythonClient.class);

    private final PythonServiceProperties pyProps;
    private final QweatherProperties qwProps;
    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public PythonClient(PythonServiceProperties pyProps, QweatherProperties qwProps) {
        this.pyProps = pyProps;
        this.qwProps = qwProps;
    }

    private HttpRequest.Builder builder(String path) {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(pyProps.baseUrl() + path))
                .header("Content-Type", "application/json");
        String workspace = com.tianchuang.config.WorkspaceContext.current();
        if (workspace != null && !workspace.isBlank()) {
            builder.header(com.tianchuang.config.WorkspaceContext.HEADER, workspace);
        }
        String operator = com.tianchuang.config.OperatorContext.current();
        if (operator != null && !operator.isBlank()) {
            builder.header(com.tianchuang.config.OperatorContext.HEADER, operator);
        }
        return builder;
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> currentWeather(int hours) throws Exception {
        String url = "/weather/current?hours=" + hours
                + "&lat=" + qwProps.lat() + "&lon=" + qwProps.lon();
        HttpRequest req = builder(url).timeout(Duration.ofSeconds(15)).GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("真实气象服务 HTTP " + resp.statusCode() + ": " + abbreviate(resp.body()));
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> track2(String runId, long deadlineEpochMs, WeatherSnapshot snap,
                                      List<ForecastHour> forecast, String region, String taskType) throws Exception {
        Map<String, Object> body = Map.of(
                "run_id", runId,
                "deadline_epoch_ms", deadlineEpochMs,
                "snapshot", mapper.convertValue(snap, Map.class),
                "forecast", forecast.stream().map(f -> mapper.convertValue(f, Map.class)).toList(),
                "region", region,
                "task_type", taskType);
        HttpRequest req = builder("/track2")
                .timeout(Duration.ofSeconds(22))
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("轨2 服务 HTTP " + resp.statusCode() + ": " + abbreviate(resp.body()));
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> ask(String question, String context) throws Exception {
        Map<String, Object> body = Map.of("question", question, "context", context);
        HttpRequest req = builder("/agent/ask")
                .timeout(Duration.ofSeconds(60))
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("问答服务 HTTP " + resp.statusCode());
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    public org.springframework.http.ResponseEntity<String> rawGet(String path) throws Exception {
        HttpRequest req = builder(path).timeout(Duration.ofSeconds(15)).GET().build();
        java.net.http.HttpResponse<String> resp = http.send(req, java.net.http.HttpResponse.BodyHandlers.ofString());
        String contentType = resp.headers().firstValue("content-type").orElse("text/plain; charset=utf-8");
        return org.springframework.http.ResponseEntity.status(resp.statusCode())
                .header("Content-Type", contentType)
                .header("Cache-Control", "no-store")
                .body(resp.body());
    }

    /**
     * 原样转发二进制响应（高程瓦片用）。
     * 走 ofString 会把 PNG 变成乱码字符串，必须用 ofByteArray。
     */
    public org.springframework.http.ResponseEntity<byte[]> rawBytes(String path) throws Exception {
        HttpRequest req = builder(path).timeout(Duration.ofSeconds(30)).GET().build();
        HttpResponse<byte[]> resp = http.send(req, HttpResponse.BodyHandlers.ofByteArray());
        // 只有成功才允许长缓存。失败响应一旦被浏览器缓存住，
        // 地图会一直拿着一份"错误内容"当瓦片用（实测：500 被缓存 7 天，地形永远出不来）。
        var builder = org.springframework.http.ResponseEntity.status(resp.statusCode())
                .header("Content-Type", resp.headers().firstValue("content-type").orElse("application/octet-stream"))
                .header("Access-Control-Allow-Origin", "*");
        if (resp.statusCode() / 100 == 2) {
            builder.header("Cache-Control", "public, max-age=604800");
        } else {
            builder.header("Cache-Control", "no-store");
        }
        return builder.body(resp.body());
    }

    /**
     * 原样透传上游 JSON（V1.1.5）。
     *
     * `decisionRequest` 会把 600 KB 的全国载荷 `readValue(..., Object.class)` 解析成一棵
     * LinkedHashMap，再交给 Jackson 重新序列化一次 —— 两条都是纯 CPU。实测：Python 侧
     * 命中缓存只要 44 ms，经这道转发变成 5 s/请求、6 并发 5.2 s（审计 P1-1 的真凶之一）。
     * 这两条热路径（nation / nation/flights）只做转发，不读字段，所以直接搬字节。
     */
    public org.springframework.http.ResponseEntity<byte[]> decisionRaw(String path, Map<String, Object> body) throws Exception {
        HttpRequest.Builder requestBuilder = builder(path).timeout(Duration.ofSeconds(75));
        if (body == null) requestBuilder.GET();
        else requestBuilder.POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)));
        HttpResponse<byte[]> response = http.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofByteArray());

        if (response.statusCode() == 304) {
            var notModified = org.springframework.http.ResponseEntity.status(304);
            response.headers().firstValue("etag").ifPresent(value -> notModified.header("ETag", value));
            response.headers().firstValue("cache-control").ifPresent(value -> notModified.header("Cache-Control", value));
            return notModified.build();
        }
        if (response.statusCode() >= 400) {
            String message = "决策请求被拒绝，请检查输入、时次或记录是否存在";
            try {
                var errorBody = mapper.readTree(response.body());
                var detail = errorBody.path("detail");
                if (detail.isTextual() && detail.asText().length() <= 160) {
                    message = detail.asText();
                } else if (detail.isArray() && detail.size() > 0) {
                    message = detail.get(0).path("msg").asText(message);
                }
            } catch (Exception ignored) {
                // 上游不是 JSON（502 页面之类）就保留默认文案，别在错误路径上再抛一次
            }
            byte[] err = mapper.writeValueAsBytes(Map.of("code", "DECISION_REQUEST_FAILED",
                    "message", message, "retryable", false));
            return org.springframework.http.ResponseEntity.status(response.statusCode())
                    .contentType(new org.springframework.http.MediaType("application", "json", java.nio.charset.StandardCharsets.UTF_8))
                    .body(err);
        }
        var ok = org.springframework.http.ResponseEntity.ok();
        response.headers().firstValue("etag").ifPresent(value -> ok.header("ETag", value));
        response.headers().firstValue("cache-control").ifPresent(value -> ok.header("Cache-Control", value));
        return ok.contentType(new org.springframework.http.MediaType("application", "json", java.nio.charset.StandardCharsets.UTF_8))
                .body(response.body());
    }

    public org.springframework.http.ResponseEntity<?> decisionRequest(String path, Map<String, Object> body) throws Exception {
        // V1.1.2：30 s 短于冷启动重建全国载荷的耗时（实测 30.2 s 断在一次 568 KB 的 GET 上，
        // 报 java.net.http.HttpTimeoutException，前端 90 s 超时被网关抢先）。抬到 75 s，
        // 留 15 s 给前端超时收尾。
        HttpRequest.Builder requestBuilder = builder(path).timeout(Duration.ofSeconds(75));
        if (body == null) requestBuilder.GET();
        else requestBuilder.POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)));
        HttpResponse<String> response = http.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() >= 400) {
            String message = "决策请求被拒绝，请检查输入、时次或记录是否存在";
            var errorBody = mapper.readTree(response.body());
            var detail = errorBody.path("detail");
            if (detail.isTextual() && detail.asText().length() <= 160) {
                message = detail.asText();
            } else if (detail.isArray() && detail.size() > 0) {
                var first = detail.get(0);
                StringBuilder where = new StringBuilder();
                var loc = first.path("loc");
                if (loc.isArray()) {
                    for (var node : loc) {
                        if (where.length() > 0) where.append('.');
                        where.append(node.asText());
                    }
                }
                String why = first.path("msg").asText("");
                if (!why.isEmpty()) message = (where.isEmpty() ? "" : where + "：") + why;
            }
            return org.springframework.http.ResponseEntity.status(response.statusCode()).body(
                    Map.of("code", "DECISION_REQUEST_FAILED", "message", message, "retryable", false));
        }
        // 304：Python 侧已经按 If-None-Match 判过，这里必须原样转出去。
        // 以前没有这一支，304 会掉进下面的 readValue("")，抛 JsonMappingException 变成 500
        // —— "浏览器缓存命中"反而变成"接口挂了"（V1.1.5）。
        if (response.statusCode() == 304) {
            var notModified = org.springframework.http.ResponseEntity.status(304);
            response.headers().firstValue("etag").ifPresent(value -> notModified.header("ETag", value));
            response.headers().firstValue("cache-control").ifPresent(value -> notModified.header("Cache-Control", value));
            return notModified.build();
        }
        var ok = org.springframework.http.ResponseEntity.ok();
        var etag = response.headers().firstValue("etag");
        var cacheControl = response.headers().firstValue("cache-control");
        etag.ifPresent(value -> ok.header("ETag", value));
        cacheControl.ifPresent(value -> ok.header("Cache-Control", value));
        return ok.body(mapper.readValue(response.body(), Object.class));
    }

    public java.util.List<com.tianchuang.dto.LayerDto> weatherLayers(Map<String, Object> dashboard) throws Exception {
        HttpRequest request = builder("/weather/layers")
                .timeout(Duration.ofSeconds(8))
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(dashboard))).build();
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) throw new IllegalStateException("天气计算服务不可用");
        return mapper.readValue(response.body(), mapper.getTypeFactory().constructCollectionType(
                java.util.List.class, com.tianchuang.dto.LayerDto.class));
    }

    private String abbreviate(String s) {
        return s == null ? "" : s.substring(0, Math.min(200, s.length()));
    }
}
