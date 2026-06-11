# Precise Prefix Cache — Migration Analysis: v0.5.1 → v0.7.0

## TL;DR

The v0.5.1 charts (`llm-d-infra`, `llm-d-modelservice`, GAIE `inferencepool`) are **no longer used** in v0.7.0.  
The entire deployment model was rebuilt: Helmfile → Helm + Kustomize, three charts → one chart (router) + Kustomize overlays.  
The guide was also renamed: `precise-prefix-cache-aware` → `precise-prefix-cache-routing`.

---

## 1. Are the v0.5.1 Charts Still in Use?

**No.** All three charts from v0.5.1 have been retired:

| v0.5.1 Chart | Registry | Version | Status in v0.7.0 |
|---|---|---|---|
| `llm-d-infra/llm-d-infra` | `https://llm-d-incubation.github.io/llm-d-infra/` | v1.3.6 | **Removed entirely** — Gateway is now a plain Kustomize overlay; no chart needed |
| `inferencepool` (GAIE upstream) | `oci://registry.k8s.io/gateway-api-inference-extension/charts/inferencepool` | v1.3.1 | **Replaced** — now `llm-d-router-standalone-dev` from `oci://ghcr.io/llm-d/charts` |
| `llm-d-modelservice/llm-d-modelservice` | `https://llm-d-incubation.github.io/llm-d-modelservice/` | v0.4.7 | **Deprecated** — replaced by Kustomize overlays (`guides/recipes/modelserver/`) |

The helmfile-based deployment (`helmfile.yaml.gotmpl`) is also gone; the guide now uses:
- `helm install` for the router/EPP
- `kubectl apply -k` for the model server

---

## 2. Chart / Dependency Comparison

### v0.5.1 — Three Charts (Helmfile)

```
llm-d-infra v1.3.6          ← gateway infrastructure (GatewayClass, Istio install)
  └── gaie-inferencepool v1.3.1  ← InferencePool CRD + EPP (GAIE upstream registry)
        └── llm-d-modelservice v0.4.7  ← vLLM model server (llm-d-incubation)
```

**Orchestration:** `helmfile apply -n ${NAMESPACE}`  
**GAIE registry:** `registry.k8s.io/gateway-api-inference-extension/charts/inferencepool`

### v0.7.0 — One Chart + Kustomize

```
llm-d-router-standalone-dev v0  ← InferencePool CRD + EPP + Envoy sidecar (llm-d registry)
kubectl apply -k modelserver/   ← vLLM Deployment (Kustomize, no chart)
```

**Orchestration:** `helm install + kubectl apply -k`  
**Router registry:** `oci://ghcr.io/llm-d/charts/llm-d-router-standalone-dev`

> The GAIE chart registry moved from `registry.k8s.io` (upstream GAIE) to `ghcr.io/llm-d` (llm-d project).  
> The GAIE CRD version jumped from **v1.3.1 → v1.5.0** (`v1-manifests.yaml`).

---

## 3. EPP / Router Comparison

| Parameter | v0.5.1 | v0.7.0 |
|---|---|---|
| **Image** | `ghcr.io/llm-d/llm-d-inference-scheduler:v0.6.0` | `ghcr.io/llm-d/llm-d-router-endpoint-picker-dev:main` |
| **Plugin config apiVersion** | `inference.networking.x-k8s.io/v1alpha1` | **`llm-d.ai/v1alpha1`** |
| **Tokenizer sidecar** | `llm-d-uds-tokenizer:v0.6.0` (UDS socket `/tmp/tokenizer/tokenizer-uds.socket`) | `vllm-render` HTTP (`http://localhost:8000`) |
| **Scorer** | `precise-prefix-cache-scorer` ← deprecated | `precise-prefix-cache-producer` + `prefix-cache-scorer` |
| **Picker** | `max-score-picker` | Removed; `no-hit-lru-scorer` added |
| **ZMQ port** | 5557 | **5556** |
| **Pod discovery** | Optional (`POD_DISCOVERY=true`), default **false** | Always **true** (`discoverPods: true`) |
| **HA replicas** | 1 | **2 (active-active)**, `ha-enable-leader-election: false` |
| **Log verbosity** | `v: 4` | `v: 2` |
| **Scheduling profiles** | Single `default` profile | Single `default` profile (same, different weights) |
| **Monitoring auth secret** | `kv-events-gateway-sa-metrics-reader-secret` | Not required in base config |

---

## 4. Model Server Comparison

| Parameter | v0.5.1 | v0.7.0 |
|---|---|---|
| **Image** | `ghcr.io/llm-d/llm-d-cuda:v0.5.1` (custom llm-d) | **`vllm/vllm-openai:v0.19.1`** (upstream) |
| **GPU resources** | Implicit (derived from `parallelism.tensor: 2`) | Explicit `nvidia.com/gpu: 2` in limits/requests |
| **ZMQ endpoint** | `tcp://gaie-<name>-epp:5557` (centralized) OR `tcp://*:5557` (pod-discovery) | Always **`tcp://*:5556`** (per-pod) |
| **KV topic format** | `kv@$(POD_IP)@<model>` | **`kv@$(POD_IP):$(POD_PORT)@<model>`** — port added |
| **Access log flag** | `--disable-uvicorn-access-log` | `--disable-access-log-for-endpoints=/health,/metrics,/v1/models` |
| **tensor-parallel-size** | Implicit via `parallelism.tensor: 2` | Explicit `--tensor-parallel-size=2` |
| **startup failureThreshold** | 60 (30 min) | **120 (60 min)** |
| **`DO_NOT_TRACK` env** | Not set | `"1"` — disables vLLM telemetry (OpenShift compat) |
| **`/.triton` + `/.config` mounts** | Partial | Added — required for OpenShift SecurityContext |
| **`GAIE_RELEASE_NAME_POSTFIX` env** | Present (helmfile coupling) | **Removed** |
| **Deployment tool** | `llm-d-modelservice` Helm chart | Kustomize overlay |

---

## 5. Istio / Gateway Comparison

### v0.5.1 — Istio as Default Gateway (Helmfile-managed)

```yaml
# guides/prereq/gateway-provider/istio.helmfile.yaml
releases:
  - name: istio-base
    chart: istio/base
    version: 1.28.1         # ← Istio 1.28.x
  - name: istiod
    chart: istio/istiod
    version: 1.28.1
    values:
      - meshConfig:
          defaultConfig:
            proxyMetadata:
              ENABLE_GATEWAY_API_INFERENCE_EXTENSION: "true"
        pilot:
          env:
            ENABLE_GATEWAY_API_INFERENCE_EXTENSION: "true"
```

- **Installation:** `helmfile` (two Helm releases: `istio-base` + `istiod`)
- **Istio version:** `1.28.1`
- **Inference extension flag:** set in both `meshConfig.defaultConfig.proxyMetadata` AND `pilot.env`
- **Istio was the default provider** — all guides assumed Istio unless `-e gke` was passed
- **DestinationRule** configured inside GAIE values per-guide (connection pool limits 256k)
- **No AgentGateway** option at v0.5.1

### v0.7.0 — Standalone (Envoy Sidecar) as Default, Istio as Optional

**Standalone is now the default** — the `precise-prefix-cache-routing` guide uses the standalone chart (Envoy sidecar inside EPP pod) and does **not require a Gateway**.

For Istio Gateway Mode:

```bash
# Step 1: Install GAIE and Gateway API CRDs
GATEWAY_API_VERSION=v1.5.1
GAIE_VERSION=v1.5.0
kubectl apply -k "https://github.com/kubernetes-sigs/gateway-api/config/crd?ref=${GATEWAY_API_VERSION}"
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${GAIE_VERSION}/v1-manifests.yaml

# Step 2: Install Istio via istioctl (not helmfile)
ISTIO_VERSION=1.29.2
istioctl install -y --set values.pilot.env.ENABLE_GATEWAY_API_INFERENCE_EXTENSION=true

# Step 3: Deploy Gateway resource (Kustomize)
kubectl apply -k ./guides/recipes/gateway/istio -n ${NAMESPACE}

# Step 4: Use the GATEWAY chart (not standalone)
helm install ${GUIDE_NAME} \
  oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev \
  -f guides/recipes/router/base.values.yaml \
  -f guides/recipes/router/features/httproute-flags.yaml \
  -f guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
  --set provider.name=istio \
  -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

| Parameter | v0.5.1 | v0.7.0 |
|---|---|---|
| **Istio version** | 1.28.1 | **1.29.2** |
| **Install method** | `helmfile` (istio-base + istiod charts) | `istioctl install` |
| **Inference ext flag** | `meshConfig.defaultConfig.proxyMetadata` + `pilot.env` | `values.pilot.env` only |
| **Istio role** | Default provider for all guides | **Optional** — standalone (Envoy sidecar) is default |
| **Router chart (Istio mode)** | GAIE `inferencepool` v1.3.1 | `llm-d-router-gateway-dev` v0 |
| **DestinationRule** | Embedded in GAIE values per-guide | Managed by chart when `provider.name=istio` |
| **HTTPRoute** | Auto-created by GAIE chart | Opt-in via `features/httproute-flags.yaml` |
| **AgentGateway** | Not available | **Now preferred** for new deployments (v1.1.0) |
| **kgateway** | Available (v2.1.x) | **Deprecated** — will be removed in next release |
| **GKE Gateway** | Available | Available (unchanged) |

---

## 6. GAIE / CRD Version

| | v0.5.1 | v0.7.0 |
|---|---|---|
| **GAIE version** | v1.3.1 | **v1.5.0** |
| **Gateway API CRDs** | Bundled in GAIE chart | `v1.5.1` (separate `kubectl apply -k`) |
| **InferencePool CRD group** | `inference.networking.x-k8s.io` | `inference.networking.x-k8s.io` (unchanged) |
| **Plugin config group** | `inference.networking.x-k8s.io/v1alpha1` | **`llm-d.ai/v1alpha1`** |

---

## 7. Summary — What to Update When Migrating

1. **Remove** helmfile, `llm-d-infra`, `llm-d-modelservice` chart dependencies entirely
2. **Replace** GAIE `inferencepool` chart with `llm-d-router-standalone-dev` (or `gateway-dev` if using a Gateway)
3. **Replace** `llm-d-cuda:v0.5.1` image with `vllm/vllm-openai:v0.19.1`
4. **Update** plugin config: `apiVersion: inference.networking.x-k8s.io/v1alpha1` → `llm-d.ai/v1alpha1`
5. **Replace** `precise-prefix-cache-scorer` with `precise-prefix-cache-producer` + `prefix-cache-scorer`
6. **Change** ZMQ port: `5557` → `5556`
7. **Change** topic format: `kv@$(POD_IP)@<model>` → `kv@$(POD_IP):$(POD_PORT)@<model>`
8. **Enable** pod discovery always (`discoverPods: true`)
9. **Update** GAIE CRDs: v1.3.1 → v1.5.0
10. **Update** Istio: 1.28.1 → 1.29.2, switch from helmfile to `istioctl install`
11. **Remove** `GAIE_RELEASE_NAME_POSTFIX` env var from model server

---

## 8. How to Create a Gateway in v0.7.0 (llm-d-infra is Gone)

`llm-d-infra` **no longer exists** in any active deployment path. It had two jobs in v0.5.1:

1. Install the gateway controller (e.g. Istio) — now done independently per-provider
2. Create the `Gateway` Kubernetes resource — now a plain Kustomize overlay

The only remaining reference in the repo is a stub (`docs/infra-providers/minikube/README.md`)
with content "TBD" — confirming it is not used.

### Step 1 — Install CRDs (once per cluster)

```bash
# Gateway API CRDs
kubectl apply -k "https://github.com/kubernetes-sigs/gateway-api/config/crd?ref=v1.5.1"

# GAIE (InferencePool / InferenceModel) CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.5.0/v1-manifests.yaml

# Or use the helper script in the repo:
bash guides/recipes/gateway/install-gateway-crds.sh
```

### Step 2 — Install the Gateway Controller

Pick one provider. **AgentGateway is now the preferred choice** for new deployments:

#### AgentGateway (preferred — v1.1.0)

```bash
helm upgrade --install agentgateway-crds \
  oci://cr.agentgateway.dev/charts/agentgateway-crds \
  --namespace agentgateway-system --create-namespace \
  --version v1.1.0

helm upgrade --install agentgateway \
  oci://cr.agentgateway.dev/charts/agentgateway \
  --namespace agentgateway-system --create-namespace \
  --version v1.1.0 \
  --set inferenceExtension.enabled=true
```

#### Istio (v1.29.2)

```bash
ISTIO_VERSION=1.29.2
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=${ISTIO_VERSION} sh -
export PATH="$PWD/istio-${ISTIO_VERSION}/bin:$PATH"
istioctl install -y \
  --set values.pilot.env.ENABLE_GATEWAY_API_INFERENCE_EXTENSION=true
```

> Note: Istio was installed via `helmfile` in v0.5.1 (chart version 1.28.1).  
> In v0.7.0 the recommended method is `istioctl install` (no chart).

#### GKE Gateway

GKE's built-in Gateway controller — no install required, enabled by default in GKE clusters.

#### kgateway

**Deprecated** in v0.7.0 — will be removed in the next release.

### Step 3 — Create the Gateway Resource (Kustomize)

After the controller is running, apply the matching Kustomize overlay to create
the `Gateway` resource in the guide namespace. No Helm chart involved.

```bash
export NAMESPACE="llm-d-precise-prefix-cache-routing"

# AgentGateway (preferred)
kubectl apply -k guides/recipes/gateway/agentgateway -n ${NAMESPACE}

# AgentGateway on OpenShift
kubectl apply -k guides/recipes/gateway/agentgateway-openshift -n ${NAMESPACE}

# Istio
kubectl apply -k guides/recipes/gateway/istio -n ${NAMESPACE}

# GKE (L7 ILB)
kubectl apply -k guides/recipes/gateway/gke-l7-rilb -n ${NAMESPACE}
```

Each overlay patches the base `Gateway` resource (`guides/recipes/gateway/base/gateway.yaml`)
with the correct `gatewayClassName` for the provider.

### Step 4 — Deploy the Router in Gateway Mode

Use `llm-d-router-gateway-dev` instead of `llm-d-router-standalone-dev`, and add
`features/httproute-flags.yaml` to create the `HTTPRoute`:

```bash
export GUIDE_NAME="precise-prefix-cache-routing"
export NAMESPACE="llm-d-${GUIDE_NAME}"
export ROUTER_CHART_VERSION=v0
export PROVIDER_NAME=agentgateway   # or: istio | gke | none

helm install ${GUIDE_NAME} \
  oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev \
  -f guides/recipes/router/base.values.yaml \
  -f guides/recipes/router/features/httproute-flags.yaml \
  -f guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
  --set provider.name=${PROVIDER_NAME} \
  -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

### Gateway Providers — Decision Matrix

| Provider | Status | Install method | Chart |
|---|---|---|---|
| **Standalone** (Envoy sidecar) | **Default** — no Gateway needed | — | `llm-d-router-standalone-dev` |
| **AgentGateway** v1.1.0 | **Preferred** for new deployments | Helm (`cr.agentgateway.dev`) | `llm-d-router-gateway-dev` |
| **Istio** v1.29.2 | Supported | `istioctl install` (not helmfile) | `llm-d-router-gateway-dev` |
| **GKE Gateway** | Supported | Built-in (no install) | `llm-d-router-gateway-dev` |
| **kgateway** | **Deprecated** | — | — |
| ~~llm-d-infra~~ | **Removed** | — | — |
