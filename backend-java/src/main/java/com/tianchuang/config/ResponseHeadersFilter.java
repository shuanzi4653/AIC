package com.tianchuang.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.io.IOException;

import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 两个安全响应头（V1.1.5，审计 P3-2）。
 *
 * 为什么放在 Java 而不是 nginx：这台机器是 2 核共享机，nginx 上还挂着
 * zhuheng / wisdiet / ice-travel 等站点，而且站点配置是"外层 443 + 内层 28081 + include 片段"
 * 三层结构，`add_header` 的继承规则是"子级只要写了 add_header，父级的全部失效" ——
 * 在代理层加头，风险是把现有的 `Cache-Control: no-store` 悄悄弄丢，而收益只是两个安全头。
 * 加在应用里，作用域天然只有本项目。
 *
 * 只加这两个，不碰 X-Frame-Options / HSTS / nosniff —— 那三个 nginx 已经发了，
 * 在这里重复设置会在响应里出现两遍同名头，反而不好排查。
 */
@Component
@Order(1)
public class ResponseHeadersFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        response.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
        // 页面不用定位/麦克风/摄像头；显式关掉，免得被第三方 iframe 借到权限。
        response.setHeader("Permissions-Policy", "geolocation=(), microphone=(), camera=()");
        chain.doFilter(request, response);
    }
}
