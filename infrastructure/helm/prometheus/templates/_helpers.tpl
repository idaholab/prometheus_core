{{/*
Shared helpers. Most take a dict with "root" (the chart's top-level context)
and "name" (the component, which is also its Deployment and Service name).
*/}}

{{/* Labels for every object of a component */}}
{{- define "prometheus.labels" -}}
{{ include "prometheus.selectorLabels" . }}
app.kubernetes.io/part-of: prometheus
app.kubernetes.io/version: {{ .root.Values.global.image.tag | default .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version }}
{{- end }}

{{/* Selector labels; they never change between upgrades */}}
{{- define "prometheus.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end }}

{{/*
Image reference {registry}/{repository}:{tag}. Takes a dict with root and
image ({registry, repository, tag}). registry and tag fall back to
global.image, and the tag then to the chart's appVersion.
*/}}
{{- define "prometheus.image" -}}
{{- $global := .root.Values.global.image -}}
{{- $registry := .image.registry | default $global.registry -}}
{{- $tag := .image.tag | default $global.tag | default .root.Chart.AppVersion -}}
{{- if $registry -}}
{{ printf "%s/%s:%s" $registry .image.repository $tag }}
{{- else -}}
{{ printf "%s:%s" .image.repository $tag }}
{{- end -}}
{{- end }}

{{/* imagePullSecrets for a pod spec, from global.image.pullSecrets */}}
{{- define "prometheus.pullSecrets" -}}
{{- with .Values.global.image.pullSecrets }}
imagePullSecrets:
  {{- range . }}
  - name: {{ . }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
The x-common-env block of docker-compose.yml, for a container. Emits envFrom
(the common ConfigMap, then the shared Secret, so .env wins over chart
defaults) and env with the URLs of the fixed services. Use as:

  envFrom:
    {{- include "prometheus.commonEnvFrom" . | nindent 4 }}
  env:
    {{- include "prometheus.commonEnv" . | nindent 4 }}
*/}}
{{- define "prometheus.commonEnvFrom" -}}
- configMapRef:
    name: prometheus-common
- secretRef:
    name: {{ .Values.secrets.shared }}
{{- end }}

{{- define "prometheus.commonEnv" -}}
- name: REGISTRY_URL
  value: http://litellm:4000
- name: REDIS_URL
  value: redis://redis:6379
- name: JWKS_URL
  value: http://backend:8000/.well-known/jwks.json
{{- end }}

{{/* env entry reading one key from the private Secret. Takes root and key. */}}
{{- define "prometheus.privateEnv" -}}
- name: {{ .key }}
  valueFrom:
    secretKeyRef:
      name: {{ .root.Values.secrets.private }}
      key: {{ .key }}
      optional: {{ .optional | default false }}
{{- end }}

{{/* env entries from a map of plain values, sorted by name */}}
{{- define "prometheus.plainEnv" -}}
{{- range $name, $value := . }}
- name: {{ $name }}
  value: {{ $value | toString | quote }}
{{- end }}
{{- end }}

{{/*
Pod and container security contexts: non-root, read-only root filesystem
(P1-11). Empty while podSecurity.enabled is false. Takes the root context;
"prometheus.podSecurity" goes in the pod spec, "prometheus.containerSecurity"
in each container.
*/}}
{{- define "prometheus.podSecurity" -}}
{{- if .Values.podSecurity.enabled }}
securityContext:
  runAsNonRoot: true
  runAsUser: {{ .Values.podSecurity.runAsUser }}
  runAsGroup: {{ .Values.podSecurity.runAsUser }}
  fsGroup: {{ .Values.podSecurity.runAsUser }}
  seccompProfile:
    type: RuntimeDefault
{{- end }}
{{- end }}

{{- define "prometheus.containerSecurity" -}}
{{- if .Values.podSecurity.enabled }}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
{{- end }}
{{- end }}

{{/*
startup, liveness and readiness probes. Takes a dict with path, port and
optionally readinessPath (default: path) and startupSeconds (how long startup
may take, default 120).
*/}}
{{- define "prometheus.probes" -}}
{{- $startup := .startupSeconds | default 120 -}}
startupProbe:
  httpGet:
    path: {{ .path }}
    port: {{ .port }}
  periodSeconds: 5
  failureThreshold: {{ div $startup 5 }}
livenessProbe:
  httpGet:
    path: {{ .path }}
    port: {{ .port }}
  periodSeconds: 15
  timeoutSeconds: 10
  failureThreshold: 5
readinessProbe:
  httpGet:
    path: {{ .readinessPath | default .path }}
    port: {{ .port }}
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
{{- end }}

{{/*
Init container that waits until host:port accepts TCP connections. Takes a
dict with root, name, host and port.
*/}}
{{- define "prometheus.waitFor" -}}
- name: wait-for-{{ .name }}
  image: {{ .root.Values.waitImage }}
  command:
    - sh
    - -c
    - until nc -z {{ .host }} {{ .port }}; do echo "waiting for {{ .name }}"; sleep 2; done
  {{- include "prometheus.containerSecurity" .root | nindent 2 }}
{{- end }}

{{/*
Init container that waits until LiteLLM is live. Agents register with it at
startup, and a failed first attempt only retries in the background.
*/}}
{{- define "prometheus.waitForLitellm" -}}
- name: wait-for-litellm
  image: {{ .Values.waitImage }}
  command:
    - sh
    - -c
    - until wget -q -O /dev/null http://litellm:4000/health/liveliness; do echo "waiting for litellm"; sleep 2; done
  {{- include "prometheus.containerSecurity" . | nindent 2 }}
{{- end }}

{{/*
BACKEND_PUBLIC_URL: backend.publicUrl, else derived from the ingress host
(https:// when ingress.tls is set), else http://localhost:8080 (k3d).
*/}}
{{- define "prometheus.backendPublicUrl" -}}
{{- if .Values.backend.publicUrl -}}
{{ .Values.backend.publicUrl }}
{{- else if .Values.ingress.host -}}
{{ ternary "https" "http" (gt (len .Values.ingress.tls) 0) }}://{{ .Values.ingress.host }}
{{- else -}}
http://localhost:8080
{{- end -}}
{{- end }}

{{/*
Pod annotation that rolls a pod when platform/.env changes. Pods read the
Secrets at start, so updating them alone leaves the old values running.
make cluster-deploy passes a hash of .env as envChecksum.
*/}}
{{- define "prometheus.envChecksum" -}}
{{- with .Values.envChecksum }}
checksum/env: {{ . | quote }}
{{- end }}
{{- end }}

{{/* Fail early when a component another one needs is disabled */}}
{{- define "prometheus.requires" -}}
{{- range .needs }}
{{- if not (index $.root.Values . "enabled") }}
{{- fail (printf "%s needs %s.enabled=true" $.name .) }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Extra CA certificate, opt in, for networks behind a TLS-inspecting proxy.
When extraCaCert.configMap names a ConfigMap with a ca.crt key, an init
container running the component's own image appends it to that image's CA
bundle in an emptyDir, and SSL_CERT_FILE and REQUESTS_CA_BUNDLE point there.
Every helper renders nothing while extraCaCert.configMap is empty.

"prometheus.caInit" takes a dict with root and image; the others take root.
*/}}
{{- define "prometheus.caInit" -}}
{{- if .root.Values.extraCaCert.configMap }}
- name: ca-bundle
  image: {{ .image }}
  command:
    - sh
    - -c
    - |
      set -e
      base=""
      for f in "$SSL_CERT_FILE" /etc/ssl/certs/ca-certificates.crt /etc/ssl/cert.pem; do
        if [ -n "$f" ] && [ -s "$f" ]; then base="$f"; break; fi
      done
      cat $base /extra-ca/ca.crt > /ca-bundle/ca-bundle.pem
  volumeMounts:
    - name: extra-ca
      mountPath: /extra-ca
      readOnly: true
    - name: ca-bundle
      mountPath: /ca-bundle
  {{- include "prometheus.containerSecurity" .root | nindent 2 }}
{{- end }}
{{- end }}

{{- define "prometheus.caEnv" -}}
{{- if .Values.extraCaCert.configMap }}
- name: SSL_CERT_FILE
  value: /ca-bundle/ca-bundle.pem
- name: REQUESTS_CA_BUNDLE
  value: /ca-bundle/ca-bundle.pem
{{- end }}
{{- end }}

{{- define "prometheus.caVolumeMounts" -}}
{{- if .Values.extraCaCert.configMap }}
- name: ca-bundle
  mountPath: /ca-bundle
  readOnly: true
{{- end }}
{{- end }}

{{- define "prometheus.caVolumes" -}}
{{- if .Values.extraCaCert.configMap }}
- name: extra-ca
  configMap:
    name: {{ .Values.extraCaCert.configMap }}
- name: ca-bundle
  emptyDir: {}
{{- end }}
{{- end }}
