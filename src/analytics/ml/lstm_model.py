import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import logging
from typing import List, Dict, Optional, Tuple, Union
from pathlib import Path

logger = logging.getLogger(__name__)

class QuantileLoss(nn.Module):
    def __init__(self, quantiles: List[float]):
        super().__init__()
        self.quantiles = quantiles

    def forward(self, preds: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """
        preds: (batch_size, num_quantiles)
        target: (batch_size, 1)
        """
        assert preds.shape[1] == len(self.quantiles)
        loss = 0.0
        for i, q in enumerate(self.quantiles):
            errors = target - preds[:, i:i+1]
            loss += torch.max((q - 1) * errors, q * errors).mean()
        return loss

class LSTMModel(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, num_quantiles: int, num_layers: int = 1):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_dim, num_quantiles)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch_size, seq_len, input_dim)
        if x.dim() == 2:
            x = x.unsqueeze(1) # (batch, 1, input_dim)
            
        out, _ = self.lstm(x)
        # out: (batch, seq_len, hidden_dim)
        last_out = out[:, -1, :]
        return self.fc(last_out)

class LSTMQuantileRegressor:
    def __init__(
        self, 
        quantiles: List[float] = [0.1, 0.5, 0.9],
        hidden_dim: int = 64,
        num_layers: int = 1,
        learning_rate: float = 0.001,
        batch_size: int = 32,
        epochs: int = 100,
        device: str = "cpu"
    ):
        self.quantiles = quantiles
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.epochs = epochs
        self.device = device
        
        self.model: Optional[LSTMModel] = None
        self.input_dim: Optional[int] = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> 'LSTMQuantileRegressor':
        # X: (n_samples, n_features) or (n_samples, seq_len, n_features)
        # y: (n_samples,)
        
        if X.ndim == 2:
            self.input_dim = X.shape[1]
        elif X.ndim == 3:
            self.input_dim = X.shape[2]
        else:
            raise ValueError("X must be 2D or 3D")
            
        self.model = LSTMModel(self.input_dim, self.hidden_dim, len(self.quantiles), self.num_layers).to(self.device)
        criterion = QuantileLoss(self.quantiles).to(self.device)
        optimizer = optim.Adam(self.model.parameters(), lr=self.learning_rate)
        
        X_tensor = torch.tensor(X, dtype=torch.float32).to(self.device)
        y_tensor = torch.tensor(y, dtype=torch.float32).view(-1, 1).to(self.device)
        
        dataset = torch.utils.data.TensorDataset(X_tensor, y_tensor)
        dataloader = torch.utils.data.DataLoader(dataset, batch_size=self.batch_size, shuffle=True)
        
        self.model.train()
        for epoch in range(self.epochs):
            epoch_loss = 0.0
            for batch_X, batch_y in dataloader:
                optimizer.zero_grad()
                preds = self.model(batch_X)
                loss = criterion(preds, batch_y)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item()
            
            if (epoch + 1) % 10 == 0:
                logger.info(f"Epoch {epoch+1}/{self.epochs}, Loss: {epoch_loss/len(dataloader):.4f}")
                
        return self

    def predict(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        if self.model is None:
            raise RuntimeError("Model not trained")
            
        self.model.eval()
        with torch.no_grad():
            X_tensor = torch.tensor(X, dtype=torch.float32).to(self.device)
            preds = self.model(X_tensor).cpu().numpy()
            
        result = {}
        for i, q in enumerate(self.quantiles):
            # Match GBRT format: q0.10
            q_key = f"q{q:.2f}"
            result[q_key] = preds[:, i]
            
        return result

    def save(self, path: Union[str, Path]) -> None:
        if self.model is None:
            raise RuntimeError("Model not trained")
        
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        state = {
            'state_dict': self.model.state_dict(),
            'config': {
                'quantiles': self.quantiles,
                'hidden_dim': self.hidden_dim,
                'num_layers': self.num_layers,
                'input_dim': self.input_dim
            }
        }
        torch.save(state, path)
        logger.info(f"Saved LSTM model to {path}")

    @classmethod
    def load(cls, path: Union[str, Path], device: str = "cpu") -> 'LSTMQuantileRegressor':
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found at {path}")
            
        state = torch.load(path, map_location=device)
        config = state['config']
        
        instance = cls(
            quantiles=config['quantiles'],
            hidden_dim=config['hidden_dim'],
            num_layers=config['num_layers'],
            device=device
        )
        instance.input_dim = config['input_dim']
        instance.model = LSTMModel(
            instance.input_dim, 
            instance.hidden_dim, 
            len(instance.quantiles), 
            instance.num_layers
        ).to(device)
        instance.model.load_state_dict(state['state_dict'])
        instance.model.eval()
        
        return instance
