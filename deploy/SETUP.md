# Cấu hình CD cho baseline runner

Đây là hướng dẫn bootstrap; chưa có tài nguyên AWS nào được tạo bởi kit.
Ví dụ dùng AWS commercial partition và EC2 Linux x86_64. Chưa hỗ trợ China/GovCloud.

## 1. Chuẩn bị tài nguyên hiện có

- EC2 có Docker, Compose plugin, AWS CLI v2, Python 3.11+, SSM Agent hoạt động.
- EC2 có đường HTTPS outbound đến SSM, ECR và những endpoint cần thiết. Chọn
  network theo VPC hiện có; không cần mở SSH public chỉ để dùng CD này.
- Instance profile: `AmazonSSMManagedInstanceCore` và quyền pull **đúng** ECR repo.
- Tạo private ECR repository; dùng immutable tags, giữ vài image gần nhất bằng
  lifecycle policy và giữ digest cần rollback trước khi xóa image cũ.
- Không publish model weights vào ECR image này; image chỉ chứa code baseline.

## 2. Cài các tệp điều phối lên EC2 một lần

Copy source bằng kênh quản trị hiện có; chạy các lệnh sau trong thư mục kit:

```bash
sudo install -d -m 0755 /opt/retailops
sudo install -m 0755 deploy/deploy-runner.sh /opt/retailops/deploy-runner.sh
sudo install -m 0644 compose.yaml /opt/retailops/compose.yaml
sudo install -d -o 10001 -g 10001 -m 0750 /opt/retailops/artifacts
sudo install -m 0600 inference.env.example /opt/retailops/inference.env
```

Dùng `sudoedit` điền `/opt/retailops/inference.env`. Tạo tệp root-owned
`/opt/retailops/allowed-ecr-repository` chứa **một dòng**, dạng:
`ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/REPOSITORY_NAME`.
Không có tag hoặc digest trong tệp allowlist này.

Chỉ script deploy và Compose được cài bootstrap. Khi sửa chúng sau này, cập nhật
hai tệp trên EC2 bằng cùng kênh quản trị trước khi dùng tính năng mới. CD tự động
hiện chỉ thay image; không tuyên bố tự đồng bộ host scripts hoặc migration DB.

## 3. Cấu hình GitHub và OIDC

Tạo environment `demo`, giới hạn deployment branch vào `main`. Thay các placeholder
trong JSON dưới đây. Thêm identity provider của GitHub Actions với audience
`sts.amazonaws.com` nếu tài khoản AWS chưa có. Role deploy dùng trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {"StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:OWNER/REPOSITORY:environment:demo"
    }}
  }]
}
```

Environment branch restriction cần đi cùng trust `sub` trên vì token đã dùng
environment thì `sub` không đồng thời chứa branch. Không mở trust cho mọi repo.

Policy quyền cho GitHub deploy role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
    {"Effect": "Allow", "Action": [
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:DescribeImages"
    ], "Resource": "arn:aws:ecr:REGION:ACCOUNT_ID:repository/REPOSITORY_NAME"},
    {"Effect": "Allow", "Action": "ssm:SendCommand", "Resource": [
      "arn:aws:ssm:REGION::document/AWS-RunShellScript",
      "arn:aws:ec2:REGION:ACCOUNT_ID:instance/INSTANCE_ID"
    ]},
    {"Effect": "Allow", "Action": "ssm:GetCommandInvocation", "Resource": "*"}
  ]
}
```

`AWS-RunShellScript` cho phép deploy role chạy lệnh quản trị trên instance đã chỉ
định. Chỉ gán role này cho repo/branch được bảo vệ; nếu cần thu hẹp hơn, tạo SSM
document chuyên biệt cho script triển khai. Không dùng quyền SSM trên mọi EC2.

Quyền ECR bổ sung vào instance profile:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
    {"Effect": "Allow", "Action": [
      "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"
    ], "Resource": "arn:aws:ecr:REGION:ACCOUNT_ID:repository/REPOSITORY_NAME"}
  ]
}
```

## 4. Variables và bật triển khai

Đặt **repository variables** sau (không phải secret dài hạn):

| Variable | Giá trị |
|---|---|
| `AWS_REGION` | Region EC2 và ECR |
| `AWS_ACCOUNT_ID` | 12 chữ số |
| `AWS_DEPLOY_ROLE_ARN` | ARN role OIDC đã tạo |
| `ECR_REPOSITORY` | Tên ECR repo, không có registry URL |
| `EC2_INSTANCE_ID` | EC2 cụ thể để triển khai |
| `RETAILOPS_DEPLOY_ENABLED` | `true` sau khi bootstrap xong |

Không đưa Colab/ngrok token vào job deploy. Token inference chỉ cần trên EC2 và
Colab; ngrok authtoken chỉ cần trong Colab. Chạy CI trước, sau đó workflow
`Deploy baseline runner to EC2` trên `main`. Khi flag chưa là `true`, job bị skip.

CD thành công tạo `/opt/retailops/deployed.env` chứa digest image đã kiểm tra.
Trên EC2, khi phiên Colab sẵn sàng:

```bash
cd /opt/retailops
sudo docker compose --env-file deployed.env run --rm baseline --allow-remote doctor
sudo docker compose --env-file deployed.env run --rm baseline --allow-remote evaluate
```

CI/CD thành công không có nghĩa model đang online hoặc đạt chất lượng. Đường
inference thật cần được kiểm tra riêng bằng các lệnh trên. Không chạy GPU eval
trong mỗi PR; không dùng việc ngrok đang mất kết nối để chặn mọi thay đổi code.

## Rollback

`previous.env` giữ con trỏ image đã kích hoạt ngay trước đó. Để chạy bằng bản đó:

```bash
sudo docker compose --env-file previous.env run --rm baseline --allow-remote doctor
```

Để đặt bản cũ thành bản active, gọi lại `deploy-runner.sh` với **digest đã biết**
và region; script sẽ pull/test rồi cập nhật con trỏ. Kit chưa có database nghiệp
vụ nên chưa có rollback schema. Không dùng `docker compose down -v` để đổi image.

## Nguồn tham khảo

- [GitHub OIDC với AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [AWS Systems Manager Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html)
- [ECR repository policy examples](https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-policy-examples.html)
- [EC2 stop/start](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html)
