#!/usr/bin/env bash
# Rebuilds the ClaimsOps cluster from scratch. Run from the repo root.
set -euo pipefail

kind create cluster --config kind-config.yaml

# Ingress controller, pinned to the control-plane node where port 8080 is wired
kubectl apply -f https://kind.sigs.k8s.io/examples/ingress/deploy-ingress-nginx.yaml
kubectl patch deployment ingress-nginx-controller -n ingress-nginx -p '{"spec":{"template":{"spec":{"nodeSelector":{"ingress-ready":"true"},"tolerations":[{"key":"node-role.kubernetes.io/control-plane","operator":"Equal","effect":"NoSchedule"}]}}}}'
kubectl rollout status deployment ingress-nginx-controller -n ingress-nginx --timeout=180s

# metrics-server for kubectl top and the autoscaler
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

# The app: database first, then everything else
kind load docker-image claims-api:1.0 --name claimsops
kubectl apply -f k8s/00-namespace.yaml -f k8s/10-postgres.yaml
kubectl rollout status statefulset/postgres -n claims --timeout=300s
kubectl apply -f k8s/
kubectl rollout status deployment/claims-api -n claims --timeout=300s

echo "Ready: curl localhost:8080/ready"
