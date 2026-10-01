# Terraform Configuration (Architectural Reference Only)

> [!WARNING]
> **ARCHITECTURAL REFERENCE ONLY**: The configurations in this directory are not currently used for live deployment. 
> To deploy the complete, functional Google Cloud Agent Gateway & Agent Platform demo, run the turnkey deployment script:
> ```bash
> ./scripts/deploy_gcp.sh --project YOUR_PROJECT_ID --region us-west1
> ```

---

### Context & Notes

1. **Why `deploy_gcp.sh` is used instead of Terraform:**
   * Google Cloud's **Agent Gateway** (`networkservices.googleapis.com/v1alpha1`), **Agent Registry** (`agentregistry.googleapis.com`), and **IAM Unified Access Policies** (`iam.googleapis.com/v3beta`) rely on rapid-preview API features that are not yet fully standardized across production HashiCorp Terraform providers.
   * Turnkey deployment and teardown are orchestrated natively via Python and Google Cloud REST APIs in [`scripts/deploy.py`](../scripts/deploy.py) and [`scripts/cleanup.sh`](../scripts/cleanup.sh).

2. **Note on Section #3 (IAM Bindings):**
   * Section #3 in `main.tf` illustrates an early conceptual Role-Based Access Control (RBAC) model.
   * In real Google Cloud production environments, agent governance does not use static `google_project_iam_member` blocks. Instead, Google Cloud employs **Attribute-Based Access Control (ABAC)** with Common Expression Language (CEL) conditions evaluated directly on the Agent Gateway proxy layer.
