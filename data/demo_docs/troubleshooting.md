# AgentCore Troubleshooting Guide

## Application crashes

1. Confirm that at least 500 MB of storage is available.
2. Clear the application cache from the operating system settings.
3. Update the application to the latest supported version.
4. Restart the application and capture the exact failure time.
5. If the problem continues, collect the application version, operating system version, error message, and relevant logs before escalating.

## Authentication failures

### HTTP 401

- Verify the username and password without sharing either value with support staff.
- Confirm that the token, API key, or signed request has not expired.
- Check that the device clock is synchronized when the API uses timestamped signatures.
- Reauthorize the application when a third-party identity provider is involved.
- Use the official password-reset flow when credentials may be invalid.

### HTTP 403

- Confirm that the account is active and has permission to access the requested resource.
- Verify resource-level roles, subscription entitlements, and IP allowlists.
- Contact an administrator when the permission cannot be changed by the user.

## Payment issues

### Failed payment

- Confirm the payment method has sufficient funds and supports online transactions.
- Check the payment-provider status and any transaction limits.
- Retry only after determining whether the first attempt created a transaction.
- Use a different payment method when the provider explicitly rejects the original method.

### Duplicate charge

- Do not submit another payment attempt until the existing transactions are reviewed.
- Record the order number, transaction identifiers, timestamps, amounts, currencies, and payment channel.
- Escalate to billing support for verification; do not promise an automatic refund before the transactions are confirmed.

## Network issues

### Slow page load

- Verify general network connectivity.
- Compare Wi-Fi and mobile-data behavior.
- Disable a proxy or VPN temporarily when policy allows.
- Clear the browser cache or test another supported browser.

### Connection timeout

- Check DNS, proxy, firewall, certificate, and service-health status.
- Record whether the failure is intermittent or consistently reproducible.
- Capture the endpoint, request time, request identifier, and timeout value before escalating.
