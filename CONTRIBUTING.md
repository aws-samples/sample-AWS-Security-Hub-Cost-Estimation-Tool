# Contributing to AWS Security Hub Cost Estimator

Thank you for your interest in contributing! This project welcomes contributions from the community.

## How to Contribute

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/your-feature`)
3. **Make your changes**
4. **Test your changes** thoroughly
5. **Commit your changes** (`git commit -am 'Add new feature'`)
6. **Push to the branch** (`git push origin feature/your-feature`)
7. **Create a Pull Request**

## Code Style

- Follow PEP 8 for Python code
- Use descriptive variable names
- Add comments for complex logic
- Keep functions focused and small

## Testing

- Test CloudFormation templates in a non-production account
- Verify cross-account role assumption works
- Verify read-only operations only

## Reporting Issues

- Use GitHub Issues to report bugs
- Include AWS region, account setup, and error messages
- Provide CloudFormation stack outputs if relevant

## Security

- Do not commit AWS credentials or account IDs
- Report security vulnerabilities privately via GitHub Security Advisories
- Follow AWS security best practices

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
