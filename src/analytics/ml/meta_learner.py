import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Union
from scipy.optimize import minimize

logger = logging.getLogger(__name__)

class EnsembleWeightLearner:
    """Learns optimal weights for ensemble components."""
    
    def __init__(self, components: List[str] = ["baseline", "gbrt", "retrieval"]):
        self.components = components
        self.weights = {c: 1.0 / len(components) for c in components}
        
    def fit(self, predictions: Dict[str, np.ndarray], actuals: np.ndarray) -> Dict[str, float]:
        """
        Fit weights to minimize error on validation data.
        
        Args:
            predictions: Dict mapping component name to array of predictions (n_samples,)
            actuals: Array of actual values (n_samples,)
            
        Returns:
            Learned weights.
        """
        # Ensure all components are present
        for c in self.components:
            if c not in predictions:
                logger.warning(f"Component {c} missing from predictions, skipping fit.")
                return self.weights
                
        n_samples = len(actuals)
        if n_samples == 0:
            return self.weights
            
        # Stack predictions: (n_samples, n_components)
        X = np.column_stack([predictions[c] for c in self.components])
        y = actuals
        
        # Objective function: Mean Squared Error
        def objective(w):
            # w is array of weights
            weighted_pred = np.dot(X, w)
            mse = np.mean((y - weighted_pred) ** 2)
            # Regularization to prefer uniform weights if error is similar
            reg = 0.01 * np.sum((w - 1.0/len(w))**2)
            return mse + reg
            
        # Constraints: sum(w) = 1
        constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})
        
        # Bounds: 0 <= w <= 1
        bounds = tuple((0.0, 1.0) for _ in range(len(self.components)))
        
        # Initial guess: current weights
        w0 = np.array([self.weights[c] for c in self.components])
        
        try:
            result = minimize(objective, w0, method='SLSQP', bounds=bounds, constraints=constraints)
            
            if result.success:
                new_weights = result.x
                for i, c in enumerate(self.components):
                    self.weights[c] = float(new_weights[i])
                logger.info(f"Learned new weights: {self.weights}")
            else:
                logger.warning(f"Weight optimization failed: {result.message}")
                
        except Exception as e:
            logger.error(f"Error during weight optimization: {e}")
            
        return self.weights

    def get_weights(self, context: Optional[Dict] = None) -> Dict[str, float]:
        """
        Get current weights. 
        Future: could use context (regime) to return dynamic weights.
        """
        return self.weights.copy()
