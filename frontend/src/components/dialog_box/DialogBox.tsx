import React from 'react';
import './DialogBox.css';

interface DialogBoxProps {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const DialogBox: React.FC<DialogBoxProps> = ({ message, onConfirm, onCancel }) => {
  return (
    <div className="dialog-box">
      <div className="dialog-content">
        <p>{message}</p>
        <div className="dialog-actions">
          <button className="confirm-button" onClick={onConfirm}>Confirm</button>
          <button className="cancel-button" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
};

export default DialogBox;
