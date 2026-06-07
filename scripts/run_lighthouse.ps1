<#
.SYNOPSIS
  ForensiQ — Auditoria de rapidez ABSOLUTA com o Google Lighthouse.

.DESCRIPTION
  Corre o Lighthouse (LCP, INP, CLS, TBT, Speed Index + acessibilidade e
  best-practices) contra um conjunto de páginas e guarda os relatórios
  (HTML + JSON) em docs/testing/reports/lighthouse/.

  É a auditoria de rapidez de "laboratório" — complementa os orçamentos de
  rapidez in-suite (e2e/test_performance.py), que correm no CI mas medem só o
  servidor local. O Lighthouse dá as métricas centradas no utilizador (Core
  Web Vitals). Corre-se à mão (precisa de um servidor a correr + Chrome), não
  no CI (pesado e o Fly é scale-to-zero).

  Pré-requisitos: Node.js (npx) e Google Chrome instalados.

.EXAMPLE
  # Páginas públicas (sem login):
  .\scripts\run_lighthouse.ps1 -BaseUrl http://127.0.0.1:8011 -Paths /login/

.EXAMPLE
  # Páginas autenticadas — passar o cookie JWT (ver docs/testing/ para o obter):
  .\scripts\run_lighthouse.ps1 -BaseUrl http://127.0.0.1:8011 `
      -Cookie "fq_access=eyJhbGciOi..." -Paths /dashboard/,/occurrences/,/evidences/

.NOTES
  Para arrancar um servidor com dados de teste, ver o guia em docs/testing/.
#>
param(
    [string]$BaseUrl = "http://127.0.0.1:8011",
    [string]$Cookie = "",
    [string[]]$Paths = @("/login/", "/dashboard/", "/occurrences/", "/evidences/", "/stats/")
)

$ErrorActionPreference = "Stop"
$outDir = Join-Path $PSScriptRoot "..\docs\testing\reports\lighthouse"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Cookie de autenticação → ficheiro JSON temporário (evita o inferno de aspas
# com JSON inline no Windows). O Lighthouse aceita --extra-headers=<ficheiro>.
$headersFile = $null
if ($Cookie) {
    $headersFile = Join-Path $env:TEMP "forensiq_lh_headers.json"
    "{`"Cookie`":`"$Cookie`"}" | Set-Content -Path $headersFile -Encoding utf8 -NoNewline
}

foreach ($p in $Paths) {
    $slug = ($p.Trim('/') -replace '[\\/]', '_')
    if (-not $slug) { $slug = "root" }
    $url = "$BaseUrl$p"
    Write-Host "Lighthouse → $url" -ForegroundColor Cyan

    $lhArgs = @(
        $url,
        "--quiet",
        "--chrome-flags=--headless=new --no-sandbox",
        "--only-categories=performance,accessibility,best-practices",
        "--output=html,json",
        "--output-path=$(Join-Path $outDir $slug)"
    )
    if ($headersFile) { $lhArgs += "--extra-headers=$headersFile" }

    & npx --yes lighthouse @lhArgs
}

if ($headersFile) { Remove-Item $headersFile -ErrorAction SilentlyContinue }
Write-Host "`nRelatórios em: $outDir" -ForegroundColor Green
